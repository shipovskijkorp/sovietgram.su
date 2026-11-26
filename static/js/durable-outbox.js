/* IndexedDB text outbox. One atomic read/write transaction per mutation;
   network sends are outside transactions and use a recoverable claim lease. */
(() => {
  const DB = "sovietgram-outbox-v2", STORE = "queues", MAX = 20, LEASE = 45000;
  const valid = item => item && typeof item.id === "string" &&
    /^[a-f0-9-]{36}$/i.test(item.id) && typeof item.text === "string" &&
    item.text.trim() && item.text.length <= 4096 &&
    typeof item.reply === "string" && /^\d*$/.test(item.reply) &&
      (item.quote === undefined || (typeof item.quote === "string" && Array.from(item.quote).length <= 1024 && (!item.quote || item.reply)));
  function clean(items) {
    return Array.isArray(items) ? items.filter(valid).slice(0, MAX).map(item => ({
      id:item.id, text:item.text, reply:item.reply, ...(item.quote ? {quote:item.quote} : {}), silent:!!item.silent,
      createdAt:Number(item.createdAt)||Date.now(), attempts:Math.max(0,Number(item.attempts)||0),
      state:item.state==="failed"?"failed":item.state==="sending"?"sending":"waiting",
      error:typeof item.error==="string"?item.error.slice(0,500):"",
      nextAttempt:Number(item.nextAttempt)||0,
      claim:typeof item.claim==="string"?item.claim:"",
      leaseUntil:Number(item.leaseUntil)||0,
    })) : [];
  }
  function openDB() {
    return new Promise((resolve, reject) => {
      let request, settled = false;
      const timer = window.setTimeout(() => {
        settled = true; reject(Error("IndexedDB unavailable"));
      }, 3000);
      function fail() {
        if (settled) return;
        settled = true; window.clearTimeout(timer); reject(Error("IndexedDB unavailable"));
      }
      try { request = indexedDB.open(DB, 1); } catch (_) { fail(); return; }
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE);
      };
      request.onerror = fail;
      request.onblocked = fail;
      request.onsuccess = () => {
        if (settled) { request.result.close(); return; }
        settled = true; window.clearTimeout(timer);
        const db = request.result;
        db.onversionchange = () => db.close();
        resolve(db);
      };
    });
  }
  // All tabs on this origin serialize the read/modify/write transaction on
  // the same store. Never await a network call with an open IDB transaction.
  function transaction(db, key, mutate) {
    return new Promise((resolve, reject) => {
      let tx;
      try { tx = db.transaction(STORE, "readwrite"); }
      catch (error) { reject(error); return; }
      const store = tx.objectStore(STORE);
      let result, items;
      tx.oncomplete = () => resolve({result, items});
      tx.onabort = () => reject(tx.error || Error("Outbox transaction aborted"));
      const read = store.get(key);
      read.onsuccess = () => {
        try {
          items = clean(read.result);
          result = mutate(items);
          if (items.length) store.put(items, key); else store.delete(key);
        } catch (_) { tx.abort(); }
      };
    });
  }
  async function create({key, storage, send, changed=()=>{}, delivered=()=>{}, now=Date.now}) {
    const db = await openDB();
    let items = [], busy = false, saved = true, fingerprint = "";
    function snapshot() { return items.map(({claim,leaseUntil,...item})=>({...item})); }
    function publish(next, success) {
      items = next;
      saved = success;
      const visible = snapshot();
      const signature = JSON.stringify([visible,saved]);
      if (fingerprint !== signature) {
        fingerprint = signature;
        changed(visible,saved);
      }
    }
    async function mutate(operation) {
      try {
        const response = await transaction(db,key,operation);
        publish(response.items,true);
        return response.result;
      } catch (error) {
        publish(items,false);
        throw error;
      }
    }
    // Migrate old tab-local queue only after successful IDB commit. Keep
    // stable IDs; if migration does not fit, retain the entire legacy queue.
    let legacy = [];
    try { legacy = clean(JSON.parse(storage?.getItem(key)||"[]")); } catch (_) {}
    try {
      await mutate(current => {
        const known = new Set(current.map(item=>item.id));
        const incoming = legacy.filter(item=>!known.has(item.id));
        if (current.length + incoming.length > MAX) throw Error("Queue full during migration");
        for (const item of incoming) current.push({...item,state:item.state==="failed"?"failed":"waiting",claim:"",leaseUntil:0});
        current.sort((a,b)=>a.createdAt-b.createdAt);
        return true;
      });
    } catch (error) { db.close(); throw error; }
    try { if (legacy.length) storage?.removeItem(key); } catch (_) {}
    function available(item) { return item.state!=="sending" || item.leaseUntil<=now(); }
    async function enqueue(text, reply="", silent=false, quote="") {
      const item = {id:window.SovietgramSendRetry.uuid(),text,reply:String(reply||""),...(quote?{quote}:{}),silent:!!silent,
        createdAt:now(),attempts:0,state:"waiting",error:"",nextAttempt:0,claim:"",leaseUntil:0};
      if (!valid(item)) return false;
      return mutate(current => {
        if (current.length>=MAX) return false;
        current.push(item); return true;
      });
    }
    async function discard(id) {
      return mutate(current=>{
        const index=current.findIndex(item=>item.id===id);
        if(index<0||!available(current[index]))return false;
        current.splice(index,1);return true;
      });
    }
    async function retryItem(id) {
      return mutate(current=>{
        const item=current.find(entry=>entry.id===id);
        if(!item||!available(item))return false;
        Object.assign(item,{state:"waiting",error:"",nextAttempt:0,claim:"",leaseUntil:0});
        return true;
      });
    }
    async function flush() {
      if(busy)return false;
      busy=true;
      try {
        const item=await mutate(current=>{
          const first=current[0];
          if(!first||first.state==="failed"||first.nextAttempt>now()||!available(first))return null;
          first.state="sending";first.attempts++;
          first.claim=window.SovietgramSendRetry.uuid();first.leaseUntil=now()+LEASE;
          return {...first};
        });
        if(!item)return false;
        let result;
        try { result=await send(item); }
        catch (_) { result={retry:true,error:"Нет ответа сервера"}; }
        // A crashed or frozen tab may lose its lease. Its late reply must
        // not overwrite a newer claim; server-side UUIDs prevent duplicates.
        const applied=await mutate(current=>{
          const index=current.findIndex(entry=>entry.id===item.id&&entry.claim===item.claim);
          if(index<0)return false;
          if(result?.ok){current.splice(index,1);return true;}
          const entry=current[index];
          entry.claim="";entry.leaseUntil=0;entry.error=result?.error||"Не удалось отправить сообщение";
          if(result?.retry){
            entry.state="waiting";
            const delay=Math.min(30000,1000*2**Math.min(entry.attempts,5));
            entry.nextAttempt=now()+Math.max(delay,Number(result.delay)||0);
          }else{entry.state="failed";entry.nextAttempt=0;}
          return true;
        });
        if(applied&&result?.ok){try{delivered(result,item);}catch(_){}return true;}
        return false;
      }finally{busy=false;}
    }
    return {enqueue,discard,retryItem,flush,snapshot,refresh:()=>mutate(()=>true),
      get saved(){return saved;}, durable:true};
  }
  window.SovietgramDurableOutbox={create};
})();
