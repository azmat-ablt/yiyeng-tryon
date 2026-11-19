const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type Asset = {
  id: string;
  url: string;
  created_at: string;
};

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export type Job = {
  id: string;
  status: JobStatus;
  result_url: string | null;
  error: string | null;
  created_at: string;
};

export type ClothType = "upper" | "lower" | "overall";

/** 衣柜里的自有单品 */
export type GarmentRecord = {
  id: string;
  url: string;
  name: string;
  cloth_type: ClothType;
  created_at: string;
};

/** 档案里的一条试穿记录 */
export type ArchiveItem = {
  id: string;
  result_url: string;
  garment_name: string;
  cloth_type: ClothType;
  person_url: string | null;
  cost_seconds: number | null;
  created_at: string;
};

export type ArchiveInput = {
  resultUrl: string;
  jobId?: string | null;
  personUrl?: string | null;
  garmentName: string;
  clothType: ClothType;
  costSeconds?: number | null;
};

async function readError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown };
    return typeof data.detail === "string" ? data.detail : response.statusText;
  } catch {
    return response.statusText;
  }
}

async function upload(kind: "photos" | "garments", file: File): Promise<Asset> {
  const form = new FormData();
  form.append("file", file);

  const response = await fetch(`${API_BASE}/api/${kind}`, {
    method: "POST",
    body: form,
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as Asset;
}

export function uploadPhoto(file: File): Promise<Asset> {
  return upload("photos", file);
}

/**
 * 上传衣物。
 * - save=false：只作为本次试穿素材（精选单品走这条路，不会塞满衣柜）
 * - save=true：同时收进衣柜，返回的 asset 可以直接用于试穿
 */
export async function uploadGarment(
  file: File,
  options?: { name?: string; clothType?: ClothType; save?: boolean },
): Promise<Asset> {
  const form = new FormData();
  form.append("file", file);
  if (options?.save) {
    form.append("save", "true");
    form.append("name", (options.name ?? file.name).slice(0, 60));
    form.append("cloth_type", options.clothType ?? "upper");
  }

  const response = await fetch(`${API_BASE}/api/garments`, {
    method: "POST",
    body: form,
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as Asset;
}

/* ---------------- 衣柜 ---------------- */

export async function listGarments(): Promise<GarmentRecord[]> {
  const response = await fetch(`${API_BASE}/api/garments`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as GarmentRecord[];
}

/** 删除衣柜单品：后端会同时删掉磁盘上的原图 */
export async function deleteGarment(garmentId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/garments/${garmentId}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
}

/* ---------------- 档案 ---------------- */

export async function listArchive(): Promise<ArchiveItem[]> {
  const response = await fetch(`${API_BASE}/api/archive`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as ArchiveItem[];
}

export async function saveArchive(input: ArchiveInput): Promise<ArchiveItem> {
  const response = await fetch(`${API_BASE}/api/archive`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      result_url: input.resultUrl,
      job_id: input.jobId ?? null,
      person_url: input.personUrl ?? null,
      garment_name: input.garmentName,
      cloth_type: input.clothType,
      cost_seconds: input.costSeconds ?? null,
    }),
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as ArchiveItem;
}

/** 删除档案记录：后端会同时删掉本地 results 里的成图 */
export async function deleteArchive(archiveId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/archive/${archiveId}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
}

/* ---------------- 试穿 ---------------- */

export async function createTryOn(personId: string, garmentId: string, clothType: ClothType = "upper"): Promise<Job> {
  const response = await fetch(`${API_BASE}/api/tryon`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ person_id: personId, garment_id: garmentId, cloth_type: clothType }),
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as Job;
}

export async function getJob(jobId: string): Promise<Job> {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}`, { cache: "no-store" });

  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as Job;
}

/** 探活：用于顶栏的 GPU 在线状态灯 */
export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/api/health`, { cache: "no-store" });
    return response.ok;
  } catch {
    return false;
  }
}
