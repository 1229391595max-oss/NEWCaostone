import { workspacePhases } from "./state.mjs";

const descriptions = Object.freeze({
  source: "Choose one or more CSV or XLSX files to upload.",
  recognition: "Review the recognized adapter, role, and source fields.",
  mapping: "Confirm the explicit source-to-canonical field mapping.",
  quality: "Review bounded parser and data-quality checks.",
  preview: "Inspect records from the exact standardized candidate.",
  commit: "Review the immutable data version before committing.",
});

export function toWorkspaceViewModel(state) {
  const fileName = state.upload?.fileName ?? state.upload?.source_filename;
  const role =
    state.upload?.recognition?.sourceRole ??
    state.upload?.recognition?.source_role ??
    state.upload?.source_role;
  const summary = fileName
    ? `${fileName}${role ? ` · ${role}` : ""} · ${state.uploads?.length ?? 0} source(s) ready`
    : "No source selected.";
  return {
    phase: state.phase,
    stages: [...workspacePhases],
    summary,
    description: descriptions[state.phase],
    busy: Boolean(state.busy),
    error: state.error,
  };
}

export function toReleaseControlsModel(state) {
  const versions = Array.isArray(state.versions) ? state.versions : [];
  const currentId = state.current?.dataset_version_id ?? null;
  return {
    status: state.status ?? "idle",
    error: state.error ?? null,
    currentId,
    currentVersion: state.current?.version_number ?? null,
    versions: versions.map((version) => {
      const isCurrent = version.id === currentId;
      const preparation = state.preparations?.[version.id] ?? null;
      return {
        ...version,
        isCurrent,
        preparation,
        publishable:
          version.status === "complete" &&
          (isCurrent || preparation?.status === "ready"),
      };
    }),
  };
}
