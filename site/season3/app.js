"use strict";

const season = window.OBSERVATION_SEASON;
const places = season?.places || [];
const $ = (id) => document.getElementById(id);
const copy = {
  en: {
    title: "Places we<br>return to.", season: "SEASON 3 · AN INDIVIDUAL PRACTICE",
    intro: "One familiar place. Four weeks. Each time we return, we look for something we haven’t noticed before.",
    about: "A window, a street, a corner of a room—or somewhere closer to ourselves. These photographs are small records of looking again.",
    collection: "A collection of places", invitation: "Choose a place. Stay a little while.",
    back: "All places", sequenceLabel: "RETURNING TO ONE PLACE", previous: "Previous place", next: "Next place",
    place: "Place", visit: "Visit", ongoing: "An ongoing collection",
    archive: "Photographs collected through", empty: "The photographic collection is not available yet.",
    missing: "This photograph could not be loaded.", photo: "Photograph", open: "Open", language: "Language",
    sequence: "Photographs in chronological order", other: "Other places", position: "Photograph position",
  },
  ru: {
    title: "Места, куда<br>мы возвращаемся.", season: "СЕЗОН 3 · ЛИЧНАЯ ПРАКТИКА",
    intro: "Одно знакомое место. Четыре недели. Каждый раз, возвращаясь, мы ищем то, чего раньше не замечали.",
    about: "Окно, улица, угол комнаты — или что-то ближе к нам самим. Эти фотографии — небольшие записи о том, как мы смотрим заново.",
    collection: "Коллекция мест", invitation: "Выберите место. Побудьте здесь немного.",
    back: "Все места", sequenceLabel: "ВОЗВРАЩАЯСЬ В ОДНО МЕСТО", previous: "Предыдущее место", next: "Следующее место",
    place: "Место", visit: "Взгляд", ongoing: "Коллекция продолжается",
    archive: "Фотографии собраны по", empty: "Коллекция фотографий пока недоступна.",
    missing: "Не удалось загрузить эту фотографию.", photo: "Фотография", open: "Открыть", language: "Язык",
    sequence: "Фотографии в хронологическом порядке", other: "Другие места", position: "Номер фотографии",
  },
};
let language = "en";
try { language = localStorage.getItem("photobot-season3-language") === "ru" ? "ru" : "en"; } catch {}
let activePlace = null;
let overviewScroll = 0;
let lastCard = null;
let scrollScheduled = false;

const number = (n) => String(n).padStart(2, "0");
const label = (place) => `${copy[language].place} ${number(place.number)}`;
function date(value, short = false, year = false) {
  if (!value) return "";
  return new Intl.DateTimeFormat(language === "ru" ? "ru-RU" : "en-GB", {
    day: "numeric", month: short ? "short" : "long", ...(year ? { year: "numeric" } : {}),
  }).format(new Date(`${value}T12:00:00`)).replace(/\s*г\.$/, "");
}
function range(photos) { return photos.length === 1 ? date(photos[0].date, true) : `${date(photos[0].date, true)} — ${date(photos.at(-1).date, true)}`; }
function onImageError(event) {
  const img = event.currentTarget;
  const error = document.createElement("span");
  error.className = "image-failure";
  error.textContent = copy[language].missing;
  img.replaceWith(error);
}

function renderGallery() {
  $("place-grid").replaceChildren();
  places.forEach((place, index) => {
    const button = document.createElement("button");
    button.className = "place-card";
    button.id = `card-${place.id}`;
    button.setAttribute("aria-label", `${copy[language].open} ${label(place)} · ${range(place.photos)}`);
    button.innerHTML = `<div class="cover"><img src="${place.cover}" alt="" ${index < 3 ? 'loading="eager"' : 'loading="lazy"'} decoding="async"></div><div class="card-caption"><span class="card-title">${label(place)}</span><span class="card-date">${range(place.photos)}</span></div>`;
    button.querySelector("img").addEventListener("error", onImageError);
    button.addEventListener("click", () => { lastCard = button.id; window.location.hash = place.id; });
    $("place-grid").append(button);
  });
  $("empty").hidden = places.length > 0;
  $("empty").textContent = copy[language].empty;
}

function renderSequence() {
  if (!activePlace) return;
  $("viewer-title").textContent = $("place-title").textContent = label(activePlace);
  $("place-dates").textContent = `${range(activePlace.photos)} · ${activePlace.photos.at(-1).date.slice(0, 4)}`;
  const previousPosition = Math.max(0, Number($("position").textContent.split("/")[0]) - 1);
  $("sequence").replaceChildren();
  activePlace.photos.forEach((photo, index) => {
    const figure = document.createElement("figure");
    figure.className = "visit";
    const responsive = photo.smallSrc && photo.smallWidth < photo.width
      ? `srcset="${photo.smallSrc} ${photo.smallWidth}w, ${photo.src} ${photo.width}w" sizes="(max-width: 650px) calc(100vw - 62px), (max-width: 920px) calc(100vw - 124px), 796px"`
      : "";
    figure.innerHTML = `<figcaption><time datetime="${photo.date}">${date(photo.date)}</time><span class="visit-number">${copy[language].visit} ${number(index + 1)}</span></figcaption><div class="photograph"><img src="${photo.src}" ${responsive} width="${photo.width}" height="${photo.height}" alt="${label(activePlace)}, ${copy[language].photo.toLowerCase()} ${index + 1}, ${date(photo.date)}" ${index < 2 ? 'loading="eager"' : 'loading="lazy"'} decoding="async"></div>`;
    figure.querySelector("img").addEventListener("error", onImageError);
    figure.querySelector("img").addEventListener("load", updatePosition);
    $("sequence").append(figure);
  });
  const index = places.indexOf(activePlace);
  $("previous-place").disabled = index === 0;
  $("next-place").disabled = index === places.length - 1;
  $("next-place-top").disabled = index === places.length - 1;
  $("position").textContent = `${number(Math.min(previousPosition + 1, activePlace.photos.length))} / ${number(activePlace.photos.length)}`;
}

function setLanguage(value) {
  const oldScroll = window.scrollY;
  language = value;
  try { localStorage.setItem("photobot-season3-language", language); } catch {}
  document.documentElement.lang = language;
  document.querySelectorAll("[data-copy]").forEach((el) => { el.innerHTML = copy[language][el.dataset.copy]; });
  document.querySelectorAll("[data-language]").forEach((el) => el.setAttribute("aria-pressed", String(el.dataset.language === language)));
  document.querySelectorAll(".languages").forEach((el) => el.setAttribute("aria-label", copy[language].language));
  $("sequence").setAttribute("aria-label", copy[language].sequence);
  $("position").setAttribute("aria-label", copy[language].position);
  document.querySelector(".sequence-footer nav").setAttribute("aria-label", copy[language].other);
  $("season-dates").textContent = season ? `${date(season.start, true)} — ${date(season.end, true, true)}` : "";
  $("archive-note").textContent = season?.through ? `${copy[language].archive} ${date(season.through, false, true)}.${season.status === "active" ? ` ${copy[language].ongoing}.` : ""}` : "";
  renderGallery();
  renderSequence();
  document.title = `${activePlace ? label(activePlace) : language === "en" ? "Places we return to" : "Места, куда мы возвращаемся"} — What Do You See?`;
  window.scrollTo(0, oldScroll);
}

function route() {
  const place = places.find((item) => `#${item.id}` === window.location.hash);
  if (place) {
    if (!activePlace) overviewScroll = window.scrollY;
    activePlace = place;
    $("overview").hidden = true;
    $("viewer").hidden = false;
    $("position").textContent = "";
    renderSequence();
    document.title = `${label(place)} — What Do You See?`;
    window.scrollTo(0, 0);
    $("place-title").focus({ preventScroll: true });
    updatePosition();
  } else {
    const hadPlace = Boolean(activePlace);
    activePlace = null;
    $("overview").hidden = false;
    $("viewer").hidden = true;
    document.title = `${language === "en" ? "Places we return to" : "Места, куда мы возвращаемся"} — What Do You See?`;
    if (hadPlace) {
      window.scrollTo(0, overviewScroll);
      if (lastCard) $(lastCard)?.focus({ preventScroll: true });
    }
  }
}
function updatePosition() {
  if (!activePlace) return;
  const figures = [...$("sequence").children];
  if (!figures.length) return;
  let nearest = 0;
  let distance = Infinity;
  figures.forEach((figure, index) => {
    const rect = figure.getBoundingClientRect();
    const next = Math.abs(rect.top + rect.height / 2 - window.innerHeight / 2);
    if (next < distance) { distance = next; nearest = index; }
  });
  $("position").textContent = `${number(nearest + 1)} / ${number(figures.length)}`;
}
function closePlace() { window.location.hash = ""; }
$("back").addEventListener("click", closePlace);
$("previous-place").addEventListener("click", () => { const place = places[places.indexOf(activePlace) - 1]; if (place) window.location.hash = place.id; });
$("next-place").addEventListener("click", () => { const place = places[places.indexOf(activePlace) + 1]; if (place) window.location.hash = place.id; });
$("next-place-top").addEventListener("click", () => { const place = places[places.indexOf(activePlace) + 1]; if (place) window.location.hash = place.id; });
document.querySelectorAll("[data-language]").forEach((button) => button.addEventListener("click", () => setLanguage(button.dataset.language)));
window.addEventListener("hashchange", route);
window.addEventListener("scroll", () => {
  if (!scrollScheduled) { scrollScheduled = true; requestAnimationFrame(() => { scrollScheduled = false; updatePosition(); }); }
}, { passive: true });
window.addEventListener("resize", updatePosition);
document.addEventListener("keydown", (event) => {
  if (!activePlace) return;
  if (event.key === "Escape") { closePlace(); return; }
  if (event.target.closest("button, a, input, textarea, select")) return;
  if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft"].includes(event.key)) return;
  event.preventDefault();
  const figures = [...$("sequence").children];
  const current = Math.max(0, Number($("position").textContent.split("/")[0]) - 1);
  const step = ["ArrowDown", "ArrowRight"].includes(event.key) ? 1 : -1;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  figures[Math.max(0, Math.min(figures.length - 1, current + step))]?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
});
setLanguage(language);
route();
