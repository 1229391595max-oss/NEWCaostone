export function chromeEnvironment(source = process.env) {
  const allowed = new Set(["HOME", "LANG", "LC_ALL", "PATH", "TMPDIR"]);
  return Object.fromEntries(
    Object.entries(source).filter(([name]) => allowed.has(name)),
  );
}
