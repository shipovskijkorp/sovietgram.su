/* A persistent, account-scoped deck of Easter egg messages.
   Draw once per cycle, then shuffle again without an immediate repeat. */
(function(root){
  "use strict";
  const messages=Object.freeze([
  "Одобрено Госпланом ★",
  "Производительность интерфейса повышена на 146%",
  "Дефицита сообщений не обнаружено",
  "Товарищ, ваш онлайн учтён статистикой",
  "Пятилетний план по регистрации выполняется досрочно",
  "Министерство переписки приветствует вас!",
  "Секретарь ЦК одобрил очередное нажатие.",
  "Ваш вклад в развитие звезды не останется незамеченным.",
  "Кнопка работает. Комиссия распущена.",
  "Товарищ, не отвлекайтесь от выполнения плана по сообщениям!",
  "Сегодня без дефицита. Завтра посмотрим.",
  "Госплан утвердил ещё одно нажатие.",
  "Количество звёзд на душу населения соответствует нормативу.",
  "План по нажатию звезды перевыполнен.",
  "В отделе идеологически выдержанных кнопок всё спокойно.",
  "Центральный сервер просит не стучать по нему.",
  "Ваша активность внесена в книгу почёта интерфейса.",
  "На разработку этой кнопки выделено три условных рубля.",
  "Звезда не выдаёт премии. Пока что.",
  "Нажатие принято. Ожидайте согласования в трёх экземплярах.",
  "Дирекция мессенджера выражает сдержанный оптимизм.",
  "Проверка показала: звезда действительно пятиконечная.",
  "В этой кнопке обнаружен стратегический запас юмора.",
  "План выполнен. Можно нажать ещё раз.",
  "Обнаружено превышение нормы хорошего настроения.",
  "Кнопка не подлежит приватизации.",
  "Товарищ, вы нашли важнейшую функцию мессенджера.",
  "Ревизия показала: все пять лучей на месте.",
  "Протокол нажатия засекречен. Потому что его нет.",
  "Отдел оптимизации обещает оптимизировать оптимизацию.",
  "В очереди за этой репликой никто не стоял.",
  "Ваше нажатие успешно прошло бюрократическую обработку.",
  "Звезда работает даже без собрания трудового коллектива.",
  "На следующей пятилетке звезда станет ещё золотее.",
  "Проверено: кнопка нажимается в соответствии с ГОСТом воображения.",
  "Комитет по борьбе с лишними кнопками оставил эту.",
  "Коэффициент товарищества вырос на один клик.",
  "Сообщение доставлено прямо из отдела пасхалок.",
  "Неисправностей не обнаружено. Кроме чрезмерного любопытства.",
  "Союз инженеров рекомендует продолжать переписку.",
  "План по отсутствию дефицита реплик выполнен.",
  "Внеочередное заседание звезды объявлено закрытым.",
  "Бюджет на эту реплику: ноль рублей и одна идея.",
  "Научно доказано: эта звезда ярче обычной кнопки.",
  "Товарищ, звезда устала, но держится!"
]);
  function createDeck({catalog=messages,storage=null,key="sovietgram.easter-star.v1",random=Math.random}={}){
    const unique=[...new Set(catalog)];
    const known=new Set(unique);
    if(!unique.length)throw new Error("Empty Easter egg catalog");
    let state={used:[],last:null};
    function restore(){
      if(!storage)return;
      try{
        const raw=storage.getItem(key);
        if(!raw)return;
        const data=JSON.parse(raw);
        if(!data||!Array.isArray(data.used))return;
        state={
          used:[...new Set(data.used.filter(value=>known.has(value)))],
          last:known.has(data.last)?data.last:null
        };
      }catch(_){
        // Invalid or unavailable storage must not break the button.
      }
    }
    return function next(){
      restore();
      let used=new Set(state.used);
      let remaining=unique.filter(value=>!used.has(value));
      if(!remaining.length){
        used=new Set();
        remaining=unique.filter(value=>value!==state.last);
        if(!remaining.length)remaining=unique.slice();
      }
      const chosen=remaining[Math.floor(random()*remaining.length)];
      used.add(chosen);
      state={used:[...used],last:chosen};
      if(storage){
        try{storage.setItem(key,JSON.stringify(state));}
        catch(_){storage=null;}
      }
      return chosen;
    };
  }
  const api={messages,createDeck};
  if(typeof module==="object"&&module.exports)module.exports=api;
  else root.SovietgramEasterStar=api;
})(typeof window!=="undefined"?window:globalThis);
