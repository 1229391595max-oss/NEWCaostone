import {
  applyCatalog,
  loadLanguagePreference,
  persistLanguagePreference,
  t,
} from "./i18n/catalog.mjs";
import { createProductTheater } from "./core/product-theater.mjs";

const browserDocument = typeof document === "undefined" ? null : document;
const form = browserDocument?.querySelector("[data-login-form]");
const message = browserDocument?.querySelector("[data-login-message]");
const toggle = browserDocument?.querySelector("[data-language-toggle]");
const passwordInput = browserDocument?.querySelector("#operator-password");
const loginInput = browserDocument?.querySelector("#operator-login");
const theaterRoot = browserDocument?.querySelector("[data-product-theater]");
let language = loadLanguagePreference();

if (theaterRoot) createProductTheater(theaterRoot);

export function safeNext(search) {
  const value = new URLSearchParams(search).get("next");
  return value === "/app" || /^\/admin(?:\/(?:data|status|ai))?$/.test(value ?? "")
    ? value
    : "/app";
}

function renderLanguage() {
  if (!browserDocument) return;
  browserDocument.documentElement.lang = language === "zh" ? "zh-CN" : "en";
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

form?.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.textContent = t(language, "login.signingIn");
  try {
    const response = await fetch("/api/operator/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        login_name: loginInput.value,
        password: passwordInput.value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      message.textContent = t(language, "error.signInFailed");
      return;
    }
    sessionStorage.setItem("bp_csrf_token", payload.csrf_token);
    window.location.assign(safeNext(window.location.search));
  } catch {
    message.textContent = t(language, "error.signInUnavailable");
  } finally {
    if (passwordInput) passwordInput.value = "";
  }
});

toggle?.addEventListener("click", () => {
  language = persistLanguagePreference(language === "en" ? "zh" : "en");
  renderLanguage();
});
