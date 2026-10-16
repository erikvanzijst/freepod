// Dark mode follows the operating system: the theme in index.css defines both.
export function followSystemTheme() {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const apply = () => document.documentElement.classList.toggle("dark", media.matches);
  apply();
  media.addEventListener("change", apply);
}
