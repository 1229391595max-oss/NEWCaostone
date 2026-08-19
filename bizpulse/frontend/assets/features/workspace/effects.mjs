function csrfHeaders(extra = {}) {
  return {
    ...extra,
    "X-CSRF-Token": sessionStorage.getItem("bp_csrf_token") ?? "",
  };
}

const selectedFiles = new Map();
const MAX_UPLOAD_BYTES = 8 * 1024 * 1024;

async function requestJson(path, options = {}) {
  const response = await fetch(`${path}`, {
    credentials: "same-origin",
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.code ?? "REQUEST_FAILED");
  }
  return payload;
}

export function newImportKeys() {
  return {
    workflow: `workflow-${crypto.randomUUID()}`,
    upload: `upload-${crypto.randomUUID()}`,
    commit: `commit-${crypto.randomUUID()}`,
  };
}

export function selectSourceFile(file) {
  return selectSourceFiles([
    {
      file,
      localKey: `0:${file.name}:${file.size}`,
      name: file.name,
      size: file.size,
      extension: file.name.split(".").pop()?.toLowerCase(),
    },
  ])[0];
}

export function selectSourceFiles(items) {
  return items.map((item) => {
    const extension = String(item.extension ?? "").toLowerCase();
    const accepted =
      ["csv", "xlsx"].includes(extension) &&
      item.size > 0 &&
      item.size <= MAX_UPLOAD_BYTES;
    if (accepted) selectedFiles.set(item.localKey, item.file);
    return {
      localKey: item.localKey,
      name: item.name,
      fileName: item.name,
      size: item.size,
      sizeBytes: item.size,
      mediaType: item.file?.type ?? "",
      accepted,
      error: accepted ? null : "FILE_TYPE_OR_SIZE_UNSUPPORTED",
    };
  });
}

export function clearSourceFile() {
  selectedFiles.clear();
}

export function removeSourceFile(localKey) {
  selectedFiles.delete(localKey);
}

function mediaTypeFor(file) {
  if (file.name.toLowerCase().endsWith(".csv")) return "text/csv";
  return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
}

export async function createAndUpload(
  keys,
  existingWorkflow = null,
  localKey = null,
) {
  const selectedFile = localKey
    ? selectedFiles.get(localKey)
    : selectedFiles.values().next().value;
  if (!selectedFile) throw new Error("SOURCE_FILE_REQUIRED");
  const workflow =
    existingWorkflow ??
    (
      await requestJson("/api/v1/import-workflows", {
        method: "POST",
        headers: csrfHeaders({
          "Content-Type": "application/json",
          "Idempotency-Key": keys.workflow,
        }),
        body: JSON.stringify({}),
      })
    ).workflow;
  const workflowId = workflow.id;
  return requestJson(
    `/api/v1/import-workflows/${workflowId}/uploads?filename=${encodeURIComponent(selectedFile.name)}`,
    {
      method: "POST",
      credentials: "same-origin",
      headers: csrfHeaders({
        "Content-Type": mediaTypeFor(selectedFile),
        "Idempotency-Key": keys.upload,
      }),
      body: selectedFile,
    },
  );
}

export function recognize(workflow, upload) {
  return requestJson(
    `/api/v1/import-workflows/${workflow.id}/uploads/${upload.id}/recognition`,
    {
      method: "POST",
      headers: csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ expected_revision: workflow.revision }),
    },
  );
}

export function confirmMapping(workflow, upload) {
  return requestJson(
    `/api/v1/import-workflows/${workflow.id}/uploads/${upload.id}/mapping`,
    {
      method: "PUT",
      headers: csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        expected_revision: workflow.revision,
        expected_mapping_revision: upload.mapping_revision,
        mapping: upload.recognition.suggested_mapping,
      }),
    },
  );
}

export function standardize(workflow, upload) {
  return requestJson(
    `/api/v1/import-workflows/${workflow.id}/uploads/${upload.id}/standardization`,
    {
      method: "POST",
      headers: csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ expected_revision: workflow.revision }),
    },
  );
}

export function loadPreview(workflow, upload) {
  return requestJson(
    `/api/v1/import-workflows/${workflow.id}/uploads/${upload.id}/preview?limit=10`,
  );
}

export function loadCommitPlan(workflow) {
  return requestJson(`/api/v1/import-workflows/${workflow.id}/commit-plan`);
}

export function commitWorkflow(workflow, idempotencyKey) {
  return requestJson(`/api/v1/import-workflows/${workflow.id}/commit`, {
    method: "POST",
    headers: csrfHeaders({
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    }),
    body: JSON.stringify({ expected_revision: workflow.revision }),
  });
}
