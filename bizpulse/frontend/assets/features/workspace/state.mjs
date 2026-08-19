const phases = Object.freeze([
  "source",
  "recognition",
  "mapping",
  "quality",
  "preview",
  "commit",
]);

export function initialWorkspaceState() {
  return {
    phase: "source",
    busy: false,
    workflow: null,
    upload: {},
    uploads: [],
    queue: [],
    preview: null,
    commitPlan: null,
    dedupe: null,
    conflicts: [],
    committed: null,
    error: null,
  };
}

export function reduceWorkspace(state, action) {
  switch (action.type) {
    case "queue/added": {
      const queue = [...state.queue];
      for (const descriptor of action.items ?? []) {
        if (queue.some((item) => item.localKey === descriptor.localKey)) continue;
        queue.push({
          ...descriptor,
          status: descriptor.accepted === false ? "invalid" : "ready",
          error: descriptor.error ?? null,
        });
      }
      return { ...state, phase: "source", queue, error: null };
    }
    case "queue/item-uploading":
      return updateQueueItem(state, action.localKey, {
        status: "uploading",
        error: null,
      });
    case "queue/item-uploaded": {
      const next = updateQueueItem(state, action.localKey, {
        status: "uploaded",
        upload: action.upload,
        error: null,
      });
      return withCurrentUpload({
        ...next,
        workflow: action.workflow,
        upload: state.upload?.id ? state.upload : action.upload,
      });
    }
    case "queue/item-failed":
      return updateQueueItem(state, action.localKey, {
        status: "failed",
        error: action.code ?? "REQUEST_FAILED",
      });
    case "queue/item-removed":
      return {
        ...state,
        queue: state.queue.filter((item) => item.localKey !== action.localKey),
      };
    case "queue/finished": {
      const firstUpload = state.uploads[0] ?? null;
      return {
        ...state,
        busy: false,
        phase: firstUpload ? "recognition" : "source",
        upload: firstUpload ?? {},
      };
    }
    case "upload/selected":
      return {
        ...state,
        phase: "source",
        busy: false,
        preview: null,
        commitPlan: null,
        dedupe: null,
        conflicts: [],
        error: null,
        upload: {
          fileName: action.fileName,
          sizeBytes: action.sizeBytes,
          mediaType: action.mediaType ?? "",
        },
      };
    case "request/started":
      return { ...state, busy: true, error: null };
    case "source/uploaded":
      return withCurrentUpload({
        ...state,
        busy: false,
        phase: "recognition",
        workflow: action.workflow,
        upload: { ...state.upload, ...action.upload },
      });
    case "recognition/completed":
      return withCurrentUpload({
        ...state,
        busy: false,
        phase: "mapping",
        workflow: action.workflow,
        upload: { ...state.upload, ...action.upload },
      });
    case "mapping/completed":
      return withCurrentUpload({
        ...state,
        busy: false,
        phase: "quality",
        workflow: action.workflow,
        upload: { ...state.upload, ...action.upload },
      });
    case "quality/completed":
      return withCurrentUpload({
        ...state,
        busy: false,
        phase: "quality",
        workflow: action.workflow,
        upload: { ...state.upload, ...action.upload },
      });
    case "preview/completed": {
      const { type, ...directPreview } = action;
      return {
        ...state,
        busy: false,
        phase: "preview",
        preview: action.preview ?? directPreview,
      };
    }
    case "commit/planned": {
      const { type, ...directPlan } = action;
      const plan = action.plan ?? directPlan;
      return {
        ...state,
        busy: false,
        phase: "commit",
        commitPlan: plan,
        dedupe: plan?.dedupe ?? null,
        conflicts: Array.isArray(plan?.conflicts) ? [...plan.conflicts] : [],
      };
    }
    case "commit/completed": {
      const { type, ...directResult } = action;
      return {
        ...state,
        busy: false,
        phase: "commit",
        committed: action.result ?? directResult,
      };
    }
    case "request/failed":
      return { ...state, busy: false, error: action.code ?? "REQUEST_FAILED" };
    case "source/add":
      return {
        ...state,
        phase: "source",
        busy: false,
        upload: {},
        preview: null,
        commitPlan: null,
        dedupe: null,
        conflicts: [],
        error: null,
      };
    case "source/next": {
      const nextUpload = state.uploads.find((item) => item.status === "staged");
      if (!nextUpload) return state;
      return {
        ...state,
        phase: "recognition",
        upload: nextUpload,
        preview: null,
        commitPlan: null,
        dedupe: null,
        conflicts: [],
        error: null,
      };
    }
    case "workflow/reset":
      return initialWorkspaceState();
    default:
      return state;
  }
}

function updateQueueItem(state, localKey, changes) {
  return {
    ...state,
    queue: state.queue.map((item) =>
      item.localKey === localKey ? { ...item, ...changes } : item,
    ),
  };
}

function withCurrentUpload(state) {
  const upload = state.upload;
  const identity = upload.id ?? upload.source_filename ?? upload.fileName;
  const existingIndex = state.uploads.findIndex(
    (candidate) =>
      (candidate.id ?? candidate.source_filename ?? candidate.fileName) === identity,
  );
  const uploads = [...state.uploads];
  if (existingIndex === -1) uploads.push(upload);
  else uploads[existingIndex] = upload;
  return { ...state, uploads };
}

export { phases as workspacePhases };
