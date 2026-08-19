const acceptedExtensions = new Set(["csv", "xls", "xlsx"]);

function extensionOf(name) {
  const value = String(name ?? "");
  const separator = value.lastIndexOf(".");
  return separator < 0 ? "" : value.slice(separator + 1).toLowerCase();
}

export function normalizeSelectedFiles(files) {
  return Array.from(files ?? [], (file, index) => {
    const extension = extensionOf(file?.name);
    return {
      file,
      localKey: `${index}:${String(file?.name ?? "")}:${Number(file?.size ?? 0)}`,
      name: String(file?.name ?? ""),
      size: Number(file?.size ?? 0),
      type: String(file?.type ?? ""),
      extension,
      accepted: acceptedExtensions.has(extension),
    };
  });
}

export function bindFileDropZone({ zone, input, onFiles, onState = () => {} }) {
  if (!zone || !input || typeof onFiles !== "function") {
    throw new Error("FILE_DROP_ZONE_INVALID");
  }
  const select = (files) => {
    const normalized = normalizeSelectedFiles(files);
    input.value = "";
    if (normalized.length) onFiles(normalized);
  };
  const handlers = {
    click: () => input.click(),
    keydown: (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        input.click();
      }
    },
    dragenter: (event) => {
      event.preventDefault();
      onState("dragging");
    },
    dragover: (event) => event.preventDefault(),
    dragleave: (event) => {
      event.preventDefault();
      onState("idle");
    },
    drop: (event) => {
      event.preventDefault();
      onState("idle");
      select(event.dataTransfer?.files);
    },
    change: () => select(input.files),
  };
  for (const name of ["click", "keydown", "dragenter", "dragover", "dragleave", "drop"]) {
    zone.addEventListener(name, handlers[name]);
  }
  input.addEventListener("change", handlers.change);
  return () => {
    for (const name of ["click", "keydown", "dragenter", "dragover", "dragleave", "drop"]) {
      zone.removeEventListener(name, handlers[name]);
    }
    input.removeEventListener("change", handlers.change);
  };
}
