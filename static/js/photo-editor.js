/* Local non-destructive photo editor. The original file is never uploaded by this module. */
(() => {
  const maxInput = 32 * 1024 * 1024;
  const maxPixels = 24 * 1024 * 1024;
  const maxOutputEdge = 4096;
  const ext = file => (file?.name || "").toLowerCase().split(".").pop();
  function canEdit(file) {
    return Boolean(file && file.size > 0 && file.size <= maxInput &&
      ["jpg", "jpeg", "png", "webp"].includes(ext(file)));
  }
  async function checkStatic(file) {
    if (!canEdit(file)) throw Error("Поддерживаются статичные JPEG, PNG и WebP до 32 МиБ.");
    const kind = ext(file);
    if (kind === "jpg" || kind === "jpeg") return;
    // Inspect chunk headers only, never flatten APNG or animated WebP.
    let offset = kind === "png" ? 8 : 12;
    const little = kind === "webp";
    for (let count = 0; offset + 8 <= file.size && count < 10000; count++) {
      const header = new DataView(await file.slice(offset,offset+8).arrayBuffer());
      const name = String.fromCharCode(...Array.from({length:4},(_,i)=>header.getUint8(little?i:i+4)));
      const size = header.getUint32(little?4:0,little);
      if (name === "acTL" || name === "ANIM" || name === "ANMF")
        throw Error("Анимированные изображения нельзя редактировать без потери анимации.");
      if (name === "IEND") return;
      offset += size + (little ? 8+(size%2) : 12);
      if (offset > file.size) throw Error("Некорректный файл изображения.");
      if (offset === file.size) return;
    }
    throw Error("Не удалось безопасно проверить структуру изображения.");
  }
  function geometry(w,h,rotation,crop){
    const turned = rotation%2 !== 0;
    const width=turned?h:w,height=turned?w:h;
    const x=Math.floor(width*crop.left/100),y=Math.floor(height*crop.top/100);
    const right=Math.ceil(width*(1-crop.right/100)),bottom=Math.ceil(height*(1-crop.bottom/100));
    return {width,height,x,y,cw:Math.max(1,right-x),ch:Math.max(1,bottom-y)};
  }
  window.SovietgramPhotoEditor = {canEdit,geometry};
  const $ = id => document.getElementById(id);
  const dialog=$("photoEditor"),canvas=$("photoEditorCanvas");
  if(!dialog||!canvas)return;
  const controls = {left:$("photoCropLeft"),right:$("photoCropRight"),top:$("photoCropTop"),bottom:$("photoCropBottom")};
  const brightness=$("photoBrightness"),contrast=$("photoContrast"),sizeLabel=$("photoEditorSize"),errorNode=$("photoEditorError"),flipButton=$("photoFlip");
  let session=null, loading=false, rotation=0, flip=false, saving=false;
  function resetCrop(){
    for(const input of Object.values(controls)){input.value="0";input.max="90";}
  }
  function readCrop(){
    return Object.fromEntries(Object.entries(controls).map(([k,input])=>[k,Number(input.value)]));
  }
  function syncCrop(){
    for(const [a,b] of [["left","right"],["top","bottom"]]){
      controls[a].max=String(95-Number(controls[b].value));
      controls[b].max=String(95-Number(controls[a].value));
    }
  }
  function currentGeometry(){return geometry(session.w,session.h,rotation,readCrop());}
  function filter(ctx){
    if("filter" in ctx)ctx.filter="brightness("+brightness.value+"%) contrast("+contrast.value+"%)";
  }
  function drawImage(ctx,g){
    ctx.save();filter(ctx);
    ctx.translate(g.width/2,g.height/2);
    ctx.scale(flip?-1:1,1);
    ctx.rotate(rotation*Math.PI/2);
    ctx.drawImage(session.image,-session.w/2,-session.h/2,session.w,session.h);
    ctx.restore();
  }
  function render(){
    if(!session)return;
    syncCrop();
    const g=currentGeometry(),scale=Math.min(1,720/Math.max(g.width,g.height));
    canvas.width=Math.max(1,Math.round(g.width*scale));canvas.height=Math.max(1,Math.round(g.height*scale));
    const ctx=canvas.getContext("2d");
    ctx.scale(canvas.width/g.width,canvas.height/g.height);drawImage(ctx,g);
    ctx.fillStyle="rgba(0,0,0,.60)";
    ctx.fillRect(0,0,g.width,g.y);
    ctx.fillRect(0,g.y,g.x,g.ch);
    ctx.fillRect(g.x+g.cw,g.y,g.width-g.x-g.cw,g.ch);
    ctx.fillRect(0,g.y+g.ch,g.width,g.height-g.y-g.ch);
    ctx.strokeStyle="#fff";ctx.lineWidth=2/scale;ctx.strokeRect(g.x,g.y,g.cw,g.ch);
    const outputScale=Math.min(1,maxOutputEdge/Math.max(g.cw,g.ch));
    sizeLabel.textContent=Math.max(1,Math.round(g.cw*outputScale))+" × "+Math.max(1,Math.round(g.ch*outputScale))+" px";
    flipButton.setAttribute("aria-pressed",String(flip));
  }
  function error(message=""){errorNode.textContent=message;errorNode.hidden=!message;}
  function reset(){rotation=0;flip=false;resetCrop();brightness.value=contrast.value="100";render();error();}
  function rotate(step){if(!session||saving)return;rotation=(rotation+step+4)%4;resetCrop();render();}
  $("photoRotateLeft").addEventListener("click",()=>rotate(-1));
  $("photoRotateRight").addEventListener("click",()=>rotate(1));
  flipButton.addEventListener("click",()=>{if(!saving){flip=!flip;render();}});
  $("photoEditorReset").addEventListener("click",reset);
  $("photoCropClear").addEventListener("click",()=>{resetCrop();render();});
  $("photoCropSquare").addEventListener("click",()=>{
    if(!session||saving)return;
    resetCrop();
    const g=currentGeometry();
    if(g.width>g.height)controls.left.value=controls.right.value=String(Math.round((1-g.height/g.width)*50));
    else controls.top.value=controls.bottom.value=String(Math.round((1-g.width/g.height)*50));
    render();
  });
  for(const input of [...Object.values(controls),brightness,contrast])input.addEventListener("input",render);
  function close(result=null){if(!session||saving)return;session.result=result;dialog.close();}
  $("photoEditorCancel").addEventListener("click",()=>close());
  $("photoEditorDiscard").addEventListener("click",()=>close());
  dialog.addEventListener("cancel",event=>{event.preventDefault();close();});
  dialog.addEventListener("close",()=>{
    const old=session;session=null;
    canvas.width=canvas.height=1;
    old?.image?.close?.();
    if(old?.url)URL.revokeObjectURL(old.url);
    old?.resolve(old.result||null);
  });
  $("photoEditorApply").addEventListener("click",async()=>{
    if(!session||saving)return;
    saving=true;error();
    const active=session;
    const changed=rotation||flip||Object.values(readCrop()).some(Boolean)||brightness.value!=="100"||contrast.value!=="100";
    if(!changed){saving=false;close(active.file);return;}
    dialog.querySelectorAll("button,input").forEach(el=>el.disabled=true);
    let output=null;
    try{
      const g=currentGeometry(),scale=Math.min(1,maxOutputEdge/Math.max(g.cw,g.ch));
      const target=document.createElement("canvas");
      target.width=Math.max(1,Math.round(g.cw*scale));target.height=Math.max(1,Math.round(g.ch*scale));
      const ctx=target.getContext("2d");
      ctx.scale(target.width/g.cw,target.height/g.ch);ctx.translate(-g.x,-g.y);drawImage(ctx,g);
      const jpeg=["jpg","jpeg"].includes(ext(active.file));
      const type=jpeg?"image/jpeg":"image/png";
      const blob=await new Promise((resolve,reject)=>target.toBlob(value=>value?resolve(value):reject(Error("Не удалось сохранить изображение.")),type,.92));
      target.width=target.height=1;
      const name=active.file.name.replace(/\.[^.]+$/,"").slice(0,200)+(jpeg?".jpg":".png");
      output=new File([blob],name,{type:blob.type,lastModified:Date.now()});
    }catch(e){error(e.message||"Не удалось сохранить изображение.");}
    finally{saving=false;dialog.querySelectorAll("button,input").forEach(el=>el.disabled=false);}
    if(output)close(output);
  });
  async function edit(file){
    if(session||loading)return null;
    loading=true;
    let image=null,url=null;
    try{
      await checkStatic(file);
      if(typeof createImageBitmap==="function"){
        try{image=await createImageBitmap(file,{imageOrientation:"from-image"});}catch(_){}
      }
      if(!image){
        url=URL.createObjectURL(file);image=new Image();image.src=url;await image.decode();
      }
      const w=image.width||image.naturalWidth,h=image.height||image.naturalHeight;
      if(!w||!h||w*h>maxPixels||Math.max(w,h)>8192)throw Error("Фото слишком большое для локального редактора (до 24 Мп и 8192 px).");
      return await new Promise(resolve=>{
        session={file,image,url,w,h,resolve,result:null};
        $("photoEditorFilters").hidden=!("filter" in canvas.getContext("2d"));
        reset();dialog.showModal();
      });
    }catch(e){
      image?.close?.();if(url)URL.revokeObjectURL(url);session=null;throw e;
    }finally{loading=false;}
  }
  window.SovietgramPhotoEditor.edit=edit;
})();
