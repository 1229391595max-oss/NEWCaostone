import {
  applyCatalog,
  loadLanguagePreference,
  persistLanguagePreference,
  t,
} from "./i18n/catalog.mjs";
import { createProductTheater } from "./core/product-theater.mjs";

const toggle = document.querySelector("[data-language-toggle]");
const demoStart = document.querySelector("[data-demo-start]");
const theaterRoot = document.querySelector("[data-product-theater]");
let language = loadLanguagePreference();

if (theaterRoot) createProductTheater(theaterRoot);

function renderLanguage() {
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  applyCatalog(language);
  if (toggle) {
    toggle.textContent = t(
      language,
      language === "en" ? "language.switchToChinese" : "language.switchToEnglish",
    );
    toggle.setAttribute("aria-label", t(language, "accessibility.languageToggle"));
  }
}

renderLanguage();

demoStart?.addEventListener("click", async () => {
  demoStart.disabled = true;
  demoStart.textContent = t(language, "welcome.starting");
  try {
    const response = await fetch("/api/demo/sessions", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.code ?? "DEMO_UNAVAILABLE");
    sessionStorage.setItem("bp_demo_csrf_token", payload.csrf_token);
    window.location.assign("/demo");
  } catch {
    demoStart.disabled = false;
    demoStart.textContent = t(language, "error.demoUnavailable");
  }
});

toggle?.addEventListener("click", () => {
  language = persistLanguagePreference(language === "en" ? "zh" : "en");
  renderLanguage();
});
