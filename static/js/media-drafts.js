/* Account/chat-scoped media drafts and immutable retry plans in IndexedDB.
   Compare-and-swap prevents a second tab from overwriting an active plan. */
(() => {
  const DB="sovietgram-media-drafts-v1", STORE="drafts";
  const MAX_DRAFT=100*1024*1024, MAX_TOTAL=256*1024*1024, MAX_RECORDS=20;
  const TTL=7*86400000;
  const uuid=()=>window.SovietgramSendRetry.uuid();
  const validKey=key=>/^\d+:\d+$/.test(key);
  const isFile=file=>file instanceof Blob && typeof file.name==="string" &&
    Number.isFinite(file.lastModified) && file.size>0;
  const uuidPattern=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  function valid(data){
    if(!data||data.version!==1||!["media","file","audio"].includes(data.mode)||
       !Array.isArray(data.files)||data.files.length<1||data.files.length>10||
       !data.files.every(isFile)||typeof data.caption!=="string"||data.caption.length>4096||
       typeof data.reply!=="string"||!/^\d*$/.test(data.reply)||
       typeof data.quote!=="string"||Array.from(data.quote).length>1024||
       (data.quote&&!data.reply)||typeof data.originalDraft!=="string"||
       data.originalDraft.length>4096)return false;
    if(data.scheduleDate!==undefined&&(typeof data.scheduleDate!=="string"||data.scheduleDate.length>40))return false;
    const plan=data.plan;
    if(!plan)return true;
    if(plan.scheduledFor!==undefined&&typeof plan.scheduledFor!=="string")return false;
    if(plan.mode!==data.mode||!Array.isArray(plan.batches)||plan.batches.length<1||plan.batches.length>10||
       !Number.isInteger(plan.completed)||plan.completed<0||plan.completed>plan.batches.length||
       typeof plan.originalDraft!=="string"||typeof plan.originalReply!=="string"||
       typeof plan.originalQuote!=="string")return false;
    if(!plan.batches.every(b=>b&&typeof b==="object"&&Array.isArray(b.files)))return false;
    const flat=plan.batches.flatMap(b=>b.files);
    return flat.length===data.files.length&&flat.every((f,i)=>isFile(f)&&f.size===data.files[i].size&&
      f.name===data.files[i].name&&f.type===data.files[i].type&&f.lastModified===data.files[i].lastModified)&&
      new Set(plan.batches.map(b=>b.id)).size===plan.batches.length&&
      plan.batches.every(b=>uuidPattern.test(b.id)&&Array.isArray(b.files)&&b.files.length>0&&
        typeof b.caption==="string"&&b.caption.length<=4096&&typeof b.reply==="string"&&/^\d*$/.test(b.reply)&&
        typeof b.quote==="string"&&Array.from(b.quote).length<=1024&&(!b.quote||b.reply));
  }
  function size(data){return data.files.reduce((sum,file)=>sum+file.size,0);}
  function open(){
    return new Promise((resolve,reject)=>{
      let request,done=false;
      const timer=setTimeout(()=>fail(),3000);
      function fail(){if(done)return;done=true;clearTimeout(timer);reject(Error("Локальное хранилище недоступно."));}
      try{request=indexedDB.open(DB,1);}catch(_){fail();return;}
      request.onupgradeneeded=()=>{if(!request.result.objectStoreNames.contains(STORE))
        request.result.createObjectStore(STORE,{keyPath:"key"});};
      request.onerror=request.onblocked=fail;
      request.onsuccess=()=>{
        if(done){request.result.close();return;}
        done=true;clearTimeout(timer);
        const db=request.result;db.onversionchange=()=>db.close();resolve(db);
      };
    });
  }
  function transact(db, operation){
    return new Promise((resolve,reject)=>{
      let tx;
      try{tx=db.transaction(STORE,"readwrite");}catch(e){reject(e);return;}
      const store=tx.objectStore(STORE),request=store.getAll();
      let result,failure;
      tx.oncomplete=()=>resolve(result);
      tx.onabort=()=>reject(failure||tx.error||Error("Не удалось сохранить файлы."));
      request.onsuccess=()=>{
        try{
          const now=Date.now(),records=[];
          for(const row of request.result){
            if(row.expiresAt<=now){store.delete(row.key);continue;}
            records.push(row);
          }
          result=operation(store,records,now);
        }catch(e){failure=e;tx.abort();}
      };
    });
  }
  async function create(key){
    if(!validKey(key))throw Error("Некорректный аккаунт или чат.");
    const db=await open();
    return {
      async load(){
        return transact(db,(_store,records)=>records.find(row=>row.key===key)||null);
      },
      async write(expected,data){
        if(!valid(data))throw Error("Некорректный черновик.");
        const bytes=size(data);
        if(bytes>MAX_DRAFT)throw Error("Локальный черновик ограничен 100 МиБ.");
        return transact(db,(store,records,now)=>{
          const current=records.find(row=>row.key===key);
          if((current?.revision||null)!==expected){
            const error=Error("Черновик изменён в другой вкладке. Обновите страницу.");error.conflict=true;throw error;
          }
          const others=records.filter(row=>row.key!==key);
          if(others.length>=MAX_RECORDS||others.reduce((sum,row)=>sum+row.bytes,0)+bytes>MAX_TOTAL)
            throw Error("Хранилище черновиков заполнено (20 черновиков или 256 МиБ).");
          const revision=uuid();
          store.put({key,revision,bytes,expiresAt:now+TTL,data});return revision;
        });
      },
      async remove(expected){
        return transact(db,(store,records)=>{
          const current=records.find(row=>row.key===key);
          if((current?.revision||null)!==expected){
            const error=Error("Черновик изменён в другой вкладке. Обновите страницу.");error.conflict=true;throw error;
          }
          store.delete(key);return null;
        });
      },
      close(){db.close();},
    };
  }
  window.SovietgramMediaDrafts={create,valid};
})();
