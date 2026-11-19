"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type ArchiveItem,
  type Asset,
  type ClothType,
  type GarmentRecord,
  type Job,
  checkHealth,
  createTryOn,
  deleteArchive,
  deleteGarment,
  getJob,
  listArchive,
  listGarments,
  saveArchive,
  uploadGarment,
  uploadPhoto,
} from "@/lib/api";

/* ============================================================
   ATELIER · 虚拟试衣间
   后端链路保持不变：上传人像 → 上传衣物 → 建任务 → 轮询结果
   ============================================================ */

const POLL_INTERVAL_MS = 1500;
const EXPECTED_SECONDS = 32;
const DEFAULT_SPLIT = 55;

type Preset = {
  id: string;
  name: string;
  desc: string;
  img: string;
  clothType: ClothType;
};

const PRESETS: Preset[] = [
  {
    id: "coat",
    name: "驼色长款大衣",
    desc: "双面呢 · 直筒剪裁",
    img: "/atelier/coat.jpg",
    clothType: "upper",
  },
  {
    id: "blazer",
    name: "黑色缎面西装",
    desc: "戗驳领 · 收腰",
    img: "/atelier/blazer.jpg",
    clothType: "upper",
  },
  {
    id: "knit",
    name: "米白高领针织",
    desc: "羊绒 · 罗纹",
    img: "/atelier/knit.jpg",
    clothType: "upper",
  },
];

const CLOTH_TYPES: { value: ClothType; label: string }[] = [
  { value: "upper", label: "上衣" },
  { value: "lower", label: "下装" },
  { value: "overall", label: "全身" },
];

type View = "studio" | "wardrobe" | "archive";

const NAV: { value: View; label: string }[] = [
  { value: "studio", label: "工作室" },
  { value: "wardrobe", label: "衣柜" },
  { value: "archive", label: "档案" },
];

const TYPE_LABEL: Record<ClothType, string> = {
  upper: "上衣",
  lower: "下装",
  overall: "全身",
};

function formatDay(iso: string) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}.${pad(date.getMonth() + 1)}.${pad(date.getDate())}`;
}

function stripExt(name: string) {
  return name.replace(/\.[^.]+$/, "");
}

type PhotoState = { asset: Asset; name: string; size: string } | null;
type GarmentState = {
  asset: Asset;
  name: string;
  size: string;
  presetId: string | null;
} | null;

type HistoryItem = {
  jobId: string;
  resultUrl: string;
  personUrl: string;
  garmentName: string;
  cost: number;
  clothType: ClothType;
};

function formatSize(bytes: number) {
  return bytes > 1024 * 1024
    ? `${(bytes / 1048576).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function shortId(id: string) {
  return id.slice(0, 8);
}

export default function HomePage() {
  /* ---------- 状态 ---------- */
  const [person, setPerson] = useState<PhotoState>(null);
  const [garment, setGarment] = useState<GarmentState>(null);
  const [clothType, setClothType] = useState<ClothType>("upper");

  const [job, setJob] = useState<Job | null>(null);
  const [resultUrl, setResultUrl] = useState<string | null>(null);
  const [cost, setCost] = useState<number | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [activeHistory, setActiveHistory] = useState<string | null>(null);

  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [uploadingPerson, setUploadingPerson] = useState(false);
  const [uploadingGarment, setUploadingGarment] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [split, setSplit] = useState(100);
  const [dragging, setDragging] = useState<"person" | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);

  /* 衣柜 / 档案 */
  const [view, setView] = useState<View>("studio");
  const [wardrobe, setWardrobe] = useState<GarmentRecord[]>([]);
  const [archive, setArchive] = useState<ArchiveItem[]>([]);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const [wardrobeBusy, setWardrobeBusy] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [viewPersonUrl, setViewPersonUrl] = useState<string | null>(null);

  const [opening, setOpening] = useState(true);
  const [entered, setEntered] = useState(false);

  const garmentInput = useRef<HTMLInputElement | null>(null);
  const wardrobeInput = useRef<HTMLInputElement | null>(null);
  const pollRef = useRef<number | null>(null);
  const cancelRef = useRef(false);
  const startedAt = useRef(0);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef(false);

  const busy = running || uploadingPerson || uploadingGarment;
  const ready = Boolean(person && garment) && !busy;
  const hasResult = Boolean(resultUrl) && !running;

  const personUrl = person?.asset.url ?? viewPersonUrl ?? "/atelier/model.jpg";
  const resultShown = resultUrl ?? personUrl;

  const progress = Math.min(95, Math.round((elapsed / EXPECTED_SECONDS) * 100));

  const hint = useMemo(() => {
    if (running) return `正在将「${garment?.name ?? "单品"}」贴合到你的轮廓…`;
    if (error) return "出现了一点问题，可调整素材后重试";
    if (hasResult) return "拖动金色分割线对比 · ← → 微调 · 双击复位";
    if (!person && !garment) return "先上传一张正面照片，再选一件单品";
    if (!person) return "还差一张人像照片";
    if (!garment) return "选择右侧单品，或上传自己的衣物";
    return "点击「开始试穿」，或按 Enter";
  }, [running, error, hasResult, person, garment]);

  const statusLabel = running
    ? `正在合成 · ${elapsed}s`
    : error
      ? "合成失败"
      : hasResult
        ? "试穿完成"
        : "等待试穿";

  const finishOpening = useCallback(() => {
    setEntered(true);
    setOpening((prev) => {
      if (!prev) return prev;
      window.setTimeout(() => setOpening(false), 1100);
      return prev;
    });
  }, []);

  /* ---------- 开场动画 ---------- */
  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      finishOpening();
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const dur = 2200;
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / dur);
      const el = document.getElementById("openingCount");
      if (el) el.textContent = String(Math.round(p * 100)).padStart(3, "0");
      if (p < 1) raf = requestAnimationFrame(tick);
      else window.setTimeout(finishOpening, 300);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [finishOpening]);

  useEffect(() => {
    if (!opening) return;
    const el = document.getElementById("opening");
    if (!el) return;
    const skip = () => finishOpening();
    el.addEventListener("click", skip);
    window.addEventListener("keydown", skip, { once: true });
    return () => {
      el.removeEventListener("click", skip);
      window.removeEventListener("keydown", skip);
    };
  }, [opening, finishOpening]);

  useEffect(() => {
    if (entered) document.body.classList.add("is-ready");
    return () => document.body.classList.remove("is-ready");
  }, [entered]);

  /* ---------- 计时 / 提示条 ---------- */
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setElapsed((v) => v + 1), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  /* ---------- 后端探活 ---------- */
  useEffect(() => {
    let alive = true;
    const probe = async () => {
      const ok = await checkHealth();
      if (alive) setOnline(ok);
    };
    void probe();
    const timer = window.setInterval(probe, 20000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  /* ---------- 衣柜 / 档案：读取与维护 ---------- */
  const refreshLibrary = useCallback(async () => {
    try {
      const [garments, looks] = await Promise.all([listGarments(), listArchive()]);
      setWardrobe(garments);
      setArchive(looks);
      setLibraryError(null);
    } catch (err) {
      setLibraryError(err instanceof Error ? err.message : "衣柜与档案暂时读不到");
    }
  }, []);

  useEffect(() => {
    void refreshLibrary();
  }, [refreshLibrary]);

  const go = useCallback((next: View) => {
    setView(next);
    setPendingDelete(null);
  }, []);

  /* 从衣柜取一件到工作室 */
  const selectFromWardrobe = useCallback((item: GarmentRecord) => {
    const asset: Asset = { id: item.id, url: item.url, created_at: item.created_at };
    setGarment({ asset, name: item.name, size: TYPE_LABEL[item.cloth_type], presetId: null });
    setClothType(item.cloth_type);
    setResultUrl(null);
    setCost(null);
    setJob(null);
    setActiveHistory(null);
    setSplit(100);
    setView("studio");
    setToast(`已选中「${item.name}」`);
  }, []);

  /* 往衣柜里添一件 */
  const addToWardrobe = useCallback(
    async (file: File | undefined) => {
      if (!file) return;
      if (!file.type.startsWith("image/")) {
        setToast("仅支持 JPG / PNG / WebP");
        return;
      }
      if (file.size > 10 * 1024 * 1024) {
        setToast("图片超过 10 MB，请压缩后再试");
        return;
      }
      setWardrobeBusy(true);
      try {
        await uploadGarment(file, { save: true, name: stripExt(file.name), clothType: "upper" });
        await refreshLibrary();
        setToast(`「${stripExt(file.name)}」已收进衣柜`);
      } catch (err) {
        setToast(err instanceof Error ? err.message : "入库失败");
      } finally {
        setWardrobeBusy(false);
      }
    },
    [refreshLibrary],
  );

  /* 删除衣柜单品（两步确认，后端会同时删原图） */
  const removeGarment = useCallback(
    async (item: GarmentRecord) => {
      if (pendingDelete !== item.id) {
        setPendingDelete(item.id);
        window.setTimeout(() => setPendingDelete((cur) => (cur === item.id ? null : cur)), 3500);
        return;
      }
      setPendingDelete(null);
      try {
        await deleteGarment(item.id);
        setWardrobe((prev) => prev.filter((row) => row.id !== item.id));
        if (garment?.asset.id === item.id) {
          setGarment(null);
          setResultUrl(null);
          setCost(null);
          setJob(null);
        }
        setToast("已从衣柜删除，本地原图一并清理");
      } catch (err) {
        setToast(err instanceof Error ? err.message : "删除失败");
      }
    },
    [pendingDelete, garment],
  );

  /* 打开档案里的一条记录 */
  const openArchiveItem = useCallback((item: ArchiveItem) => {
    setResultUrl(item.result_url);
    setCost(item.cost_seconds ?? null);
    setActiveHistory(item.id);
    setViewPersonUrl(item.person_url ?? null);
    setJob({
      id: item.id,
      status: "succeeded",
      result_url: item.result_url,
      error: null,
      created_at: item.created_at,
    });
    setSplit(DEFAULT_SPLIT);
    setView("studio");
    setToast(`已调出「${item.garment_name}」`);
  }, []);

  /* 删除档案记录（两步确认，后端会同时删本地成图） */
  const removeArchive = useCallback(
    async (item: ArchiveItem) => {
      if (pendingDelete !== item.id) {
        setPendingDelete(item.id);
        window.setTimeout(() => setPendingDelete((cur) => (cur === item.id ? null : cur)), 3500);
        return;
      }
      setPendingDelete(null);
      try {
        await deleteArchive(item.id);
        setArchive((prev) => prev.filter((row) => row.id !== item.id));
        setHistory((prev) => prev.filter((row) => row.jobId !== item.id));
        if (activeHistory === item.id) {
          setResultUrl(null);
          setCost(null);
          setJob(null);
          setActiveHistory(null);
          setSplit(100);
        }
        setToast("已删除，本地成图同步清理");
      } catch (err) {
        setToast(err instanceof Error ? err.message : "删除失败");
      }
    },
    [pendingDelete, activeHistory],
  );

  /* ---------- 清理轮询 ---------- */
  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  /* ---------- 上传人像 ---------- */
  const handlePhoto = useCallback(async (file: File | undefined) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("仅支持 JPG / PNG / WebP 图片");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setError("图片超过 10 MB，请压缩后再试");
      return;
    }
    setError(null);
    setUploadingPerson(true);
    try {
      const asset = await uploadPhoto(file);
      setPerson({ asset, name: file.name, size: formatSize(file.size) });
      setViewPersonUrl(null);
      setResultUrl(null);
      setCost(null);
      setActiveHistory(null);
      setSplit(100);
      setToast("人像已上传");
    } catch (err) {
      setError(err instanceof Error ? err.message : "人像上传失败");
    } finally {
      setUploadingPerson(false);
    }
  }, []);

  /* ---------- 选择预设单品：本地图上传成后端 garment ---------- */
  const selectPreset = useCallback(
    async (preset: Preset) => {
      if (busy) return;
      setError(null);
      setUploadingGarment(true);
      try {
        const response = await fetch(preset.img);
        const blob = await response.blob();
        const file = new File([blob], `${preset.id}.jpg`, { type: blob.type || "image/jpeg" });
        const asset = await uploadGarment(file);
        setGarment({
          asset,
          name: preset.name,
          size: formatSize(file.size),
          presetId: preset.id,
        });
        setClothType(preset.clothType);
        setResultUrl(null);
        setCost(null);
        setActiveHistory(null);
        setSplit(100);
      } catch (err) {
        setError(err instanceof Error ? err.message : "单品载入失败");
      } finally {
        setUploadingGarment(false);
      }
    },
    [busy],
  );

  /* ---------- 上传自有衣物 ---------- */
  const handleGarmentFile = useCallback(async (file: File | undefined) => {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("仅支持 JPG / PNG / WebP 图片");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setError("图片超过 10 MB，请压缩后再试");
      return;
    }
    setError(null);
    setUploadingGarment(true);
    try {
      const asset = await uploadGarment(file, {
        save: true,
        name: stripExt(file.name),
        clothType,
      });
      setGarment({
        asset,
        name: stripExt(file.name),
        size: formatSize(file.size),
        presetId: null,
      });
      setResultUrl(null);
      setCost(null);
      setActiveHistory(null);
      setSplit(100);
      setToast("自有单品已收进衣柜");
      void refreshLibrary();
    } catch (err) {
      setError(err instanceof Error ? err.message : "衣物上传失败");
    } finally {
      setUploadingGarment(false);
    }
  }, [clothType, refreshLibrary]);

  /* ---------- 开始试穿 ---------- */
  const handleStart = useCallback(async () => {
    if (!person || !garment || busy) return;
    const personAsset = person.asset;
    const garmentAsset = garment.asset;
    const garmentName = garment.name;
    const type = clothType;

    setError(null);
    setRunning(true);
    setElapsed(0);
    setSplit(100);
    setResultUrl(null);
    setCost(null);
    startedAt.current = performance.now();
    cancelRef.current = false;
    stopPolling();

    try {
      const created = await createTryOn(personAsset.id, garmentAsset.id, type);
      setJob(created);

      pollRef.current = window.setInterval(async () => {
        if (cancelRef.current) return;
        try {
          const latest = await getJob(created.id);
          if (cancelRef.current) return;
          setJob(latest);

          if (latest.status === "succeeded" && latest.result_url) {
            stopPolling();
            setRunning(false);
            const spent = Math.max(1, Math.round((performance.now() - startedAt.current) / 1000));
            setCost(spent);
            setResultUrl(latest.result_url);
            setSplit(DEFAULT_SPLIT);
            setActiveHistory(latest.id);
            setHistory((prev) =>
              [
                {
                  jobId: latest.id,
                  resultUrl: latest.result_url as string,
                  personUrl: personAsset.url,
                  garmentName,
                  cost: spent,
                  clothType: type,
                },
                ...prev.filter((item) => item.jobId !== latest.id),
              ].slice(0, 8),
            );
            setToast(`试穿完成 · ${spent} 秒`);

            /* 自动存入档案：失败不影响主流程 */
            void saveArchive({
              resultUrl: latest.result_url,
              jobId: latest.id,
              personUrl: personAsset.url,
              garmentName,
              clothType: type,
              costSeconds: spent,
            })
              .then((saved) => setArchive((prev) => [saved, ...prev.filter((row) => row.id !== saved.id)]))
              .catch(() => undefined);
          } else if (latest.status === "failed") {
            stopPolling();
            setRunning(false);
            setError(latest.error ?? "生成失败，请重试");
          }
        } catch (err) {
          stopPolling();
          setRunning(false);
          setError(err instanceof Error ? err.message : "查询任务失败");
        }
      }, POLL_INTERVAL_MS);
    } catch (err) {
      setRunning(false);
      setError(err instanceof Error ? err.message : "创建任务失败");
    }
  }, [person, garment, busy, clothType, stopPolling]);

  /* 停止等待（任务仍在后端继续跑） */
  const handleCancel = useCallback(() => {
    if (!running) return;
    cancelRef.current = true;
    stopPolling();
    setRunning(false);
    setToast("已停止等待，任务仍在后台运行");
  }, [running, stopPolling]);

  /* ---------- 对比拖动 ---------- */
  const setSplitByClientX = useCallback((clientX: number) => {
    const el = canvasRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const pct = Math.min(100, Math.max(0, ((clientX - rect.left) / rect.width) * 100));
    setSplit(pct);
  }, []);

  const onCanvasPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!hasResult) return;
    dragRef.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    setSplitByClientX(event.clientX);
  };
  const onCanvasPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    setSplitByClientX(event.clientX);
  };
  const onCanvasPointerUp = () => {
    dragRef.current = false;
  };

  /* ---------- 重置 ---------- */
  const handleReset = useCallback(() => {
    stopPolling();
    cancelRef.current = true;
    setRunning(false);
    setJob(null);
    setResultUrl(null);
    setCost(null);
    setSplit(100);
    setActiveHistory(null);
    setError(null);
    setToast("画面已重置");
  }, [stopPolling]);

  /* ---------- 下载 / 复制 ---------- */
  const handleDownload = useCallback(async () => {
    if (!resultUrl) {
      setToast("暂无可下载的结果");
      return;
    }
    try {
      const response = await fetch(resultUrl);
      if (!response.ok) throw new Error("download failed");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `atelier-${job ? shortId(job.id) : "result"}.png`;
      link.click();
      URL.revokeObjectURL(url);
      setToast("已开始下载");
    } catch {
      setToast("下载失败，请稍后重试");
    }
  }, [resultUrl, job]);

  const handleCopy = useCallback(async () => {
    if (!resultUrl) return;
    try {
      await navigator.clipboard.writeText(resultUrl);
      setToast("结果链接已复制");
    } catch {
      setToast("复制失败，请手动复制");
    }
  }, [resultUrl]);

  /* ---------- 快捷键 ---------- */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;

      if (event.key === "Enter" && ready) {
        event.preventDefault();
        void handleStart();
      } else if (event.key.toLowerCase() === "r") {
        handleReset();
      } else if (["1", "2", "3"].includes(event.key)) {
        const preset = PRESETS[Number(event.key) - 1];
        if (preset) void selectPreset(preset);
      } else if (hasResult && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
        event.preventDefault();
        setSplit((prev) => Math.min(100, Math.max(0, prev + (event.key === "ArrowLeft" ? -4 : 4))));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ready, hasResult, handleStart, handleReset, selectPreset]);

  /* ---------- 整页拖拽：丢到左栏=人像，丢到别处=衣物 ---------- */
  useEffect(() => {
    const onDrop = (event: DragEvent) => {
      const file = event.dataTransfer?.files?.[0];
      if (!file) return;
      event.preventDefault();
      void handleGarmentFile(file);
    };
    window.addEventListener("drop", onDrop);
    return () => window.removeEventListener("drop", onDrop);
  }, [handleGarmentFile]);

  /* ---------- 渲染 ---------- */
  const canvasClass = [
    "canvas",
    hasResult ? "has-result" : "",
    running ? "scanning" : "",
    error && !running ? "is-failed" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const modeClass = online === null ? "" : running ? "is-busy" : online ? "is-online" : "is-offline";

  return (
    <>
      {opening ? (
        <div id="opening" className={entered ? "leaving" : ""}>
          <div className="opening-inner">
            <div className="opening-mark">
              {"ATELIER".split("").map((char, index) => (
                <span key={`${char}-${index}`} style={{ ["--i" as string]: index }}>
                  {char}
                </span>
              ))}
              <span className="dot" style={{ ["--i" as string]: 7 }}>
                .
              </span>
            </div>
            <div className="opening-line" />
            <div className="opening-sub opening-sub-cn">虚拟试衣间</div>
            <div className="opening-sub opening-sub-en">Virtual Fitting Room</div>
          </div>
          <div className="opening-count" id="openingCount">
            000
          </div>
        </div>
      ) : null}

      <div className="ambient" />
      <div className="grain" />

      <header>
        <div className="brand">
          Atelier<span>.</span>
        </div>
        <nav>
          {NAV.map((item) => (
            <button
              key={item.value}
              type="button"
              className={view === item.value ? "is-active" : ""}
              onClick={() => go(item.value)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="header-right">
          <div className={`mode-tag ${modeClass}`} title="后端推理服务状态">
            <i />
            {online === null ? "连接中" : running ? "合成中" : online ? "GPU · 就绪" : "后端离线"}
          </div>
        </div>
      </header>

      <main className={`stage${view === "studio" ? "" : " is-hidden"}`} aria-hidden={view !== "studio"}>
        {/* 左栏：文案 + 人像上传 */}
        <section className="intro">
          <div className="eyebrow">Virtual Fitting Room</div>
          <h1>
            把衣服<em>试</em>
            <br />
            在身上。
          </h1>
          <p>
            上传一张正面照片，选择一件单品，系统会在几秒内合成你的试穿效果。拖动分割线可对比原始照片。
          </p>

          <label
            className={`upload${person ? " is-loaded" : ""}${dragging ? " dragover" : ""}`}
            onDragOver={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setDragging("person");
            }}
            onDragLeave={() => setDragging(null)}
            onDrop={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setDragging(null);
              void handlePhoto(event.dataTransfer.files?.[0]);
            }}
          >
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={(event) => {
                void handlePhoto(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
            <strong>
              {uploadingPerson
                ? "上传中…"
                : person
                  ? person.name.length > 16
                    ? `${person.name.slice(0, 14)}…`
                    : person.name
                  : "上传你的照片"}
            </strong>
            <small>{person ? "点击可更换，或把新照片拖到这里" : "支持 JPG / PNG，建议正面全身"}</small>
          </label>
          {person ? (
            <div className="upload-meta">
              <span>{person.size}</span>
              <span>{person.asset.id.slice(0, 8)}</span>
            </div>
          ) : null}

          {error ? (
            <div className="notice">
              <i />
              <span>{error}</span>
            </div>
          ) : null}

          <div className="kbd-hint">
            <b>Enter</b> 开始试穿 · <b>1–3</b> 换单品 · <b>R</b> 重置 · <b>← →</b> 对比
          </div>
        </section>

        {/* 中栏：画布 */}
        <section className="canvas-wrap">
          <div
            ref={canvasRef}
            className={canvasClass}
            style={{ ["--split" as string]: `${split}%` }}
            onPointerDown={onCanvasPointerDown}
            onPointerMove={onCanvasPointerMove}
            onPointerUp={onCanvasPointerUp}
            onPointerCancel={onCanvasPointerUp}
            onDoubleClick={() => hasResult && setSplit((prev) => (prev > 70 ? 50 : 100))}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img className="layer" src={personUrl} alt="人像" />
            <div className="result">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img className="layer" src={resultShown} alt="试穿效果" />
            </div>
            <div className="scan" />
            <div className="compare">
              <span>↔</span>
            </div>
            <button
              type="button"
              className={`status${running ? " is-clickable" : ""}`}
              onClick={running ? handleCancel : undefined}
              title={running ? "点击停止等待" : undefined}
            >
              <i />
              <span>{statusLabel}</span>
            </button>
          </div>
          <div className={`hint${hasResult ? " is-strong" : ""}`}>{hint}</div>
          <div className="strip">
            {history.length > 0 ? (
              <>
                <span className="strip-label">记录</span>
                {history.map((item) => (
                  <button
                    key={item.jobId}
                    type="button"
                    className={`thumb${activeHistory === item.jobId ? " is-current" : ""}`}
                    title={`${item.garmentName} · ${item.cost} 秒`}
                    onClick={() => {
                      setResultUrl(item.resultUrl);
                      setCost(item.cost);
                      setActiveHistory(item.jobId);
                      setSplit(DEFAULT_SPLIT);
                    }}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={item.resultUrl} alt={item.garmentName} />
                  </button>
                ))}
              </>
            ) : null}
          </div>
        </section>

        {/* 右栏：单品 + 操作 */}
        <aside className="rail">
          <h2>选择单品</h2>

          {PRESETS.map((preset, index) => (
            <button
              key={preset.id}
              type="button"
              className={`card${garment?.presetId === preset.id ? " active" : ""}`}
              disabled={busy && garment?.presetId !== preset.id}
              onClick={() => void selectPreset(preset)}
              title={`按 ${index + 1} 快速选择`}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={preset.img} alt="" />
              <div className="meta">
                <strong>{preset.name}</strong>
                <small>{preset.desc}</small>
              </div>
              {uploadingGarment && garment?.presetId === preset.id ? (
                <span className="card-loading" />
              ) : null}
            </button>
          ))}

          <button
            type="button"
            className={`card card--custom${garment && garment.presetId === null ? " active" : ""}`}
            onClick={() => garmentInput.current?.click()}
            disabled={busy}
          >
            <span className="plus">+</span>
            <div className="meta">
              <strong>{garment && garment.presetId === null ? garment.name : "上传自有单品"}</strong>
              <small>{garment && garment.presetId === null ? garment.size : "平铺图或穿着图"}</small>
            </div>
          </button>
          <input
            ref={garmentInput}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            hidden
            onChange={(event) => {
              void handleGarmentFile(event.target.files?.[0]);
              event.target.value = "";
            }}
          />

          <button type="button" className="wardrobe-link" onClick={() => go("wardrobe")}>
            <span>衣柜 · {wardrobe.length} 件</span>
            <span aria-hidden>→</span>
          </button>

          {garment && garment.presetId === null ? (
            <div className="type-row">
              <span>类型</span>
              {CLOTH_TYPES.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  className={clothType === item.value ? "on" : ""}
                  onClick={() => setClothType(item.value)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          ) : null}

          <button type="button" className="generate" disabled={!ready} onClick={() => void handleStart()}>
            {running ? `合成中 ${progress}%` : hasResult ? "再次试穿" : "开始试穿"}
            {running ? <span className="bar" style={{ width: `${progress}%` }} /> : null}
          </button>

          <button type="button" className="reset" onClick={handleReset}>
            重置画面
          </button>

          <div className="spec">
            <div>
              当前单品 <b>{garment?.name ?? "未选择"}</b>
            </div>
            <div>
              合成耗时 <b>{cost !== null ? `${cost} s` : running ? `${elapsed} s` : "—"}</b>
            </div>
            <div>
              画面尺寸 <b>768 × 1024</b>
            </div>
            <div>
              任务编号 <b>{job ? shortId(job.id) : "—"}</b>
            </div>
            <div>
              结果{" "}
              <b
                style={{ cursor: resultUrl ? "pointer" : "default" }}
                onClick={() => void handleDownload()}
              >
                {resultUrl ? "下载 PNG" : "—"}
              </b>
            </div>
            <div>
              分享{" "}
              <b style={{ cursor: resultUrl ? "pointer" : "default" }} onClick={() => void handleCopy()}>
                {resultUrl ? "复制链接" : "—"}
              </b>
            </div>
          </div>
        </aside>
      </main>

      {/* 衣柜 / 档案 */}
      {view !== "studio" ? (
        <main className="library">
          <div className="lib-top">
            <div className="lib-title">
              <div className="eyebrow">{view === "wardrobe" ? "Wardrobe" : "Archive"}</div>
              <h1>{view === "wardrobe" ? "我的衣柜." : "试穿档案."}</h1>
              <p>
                {view === "wardrobe"
                  ? "收在这里的单品，每次试穿都能直接取用；删除时会连本地原图一起清掉。"
                  : "试穿成功的搭配会自动归档；打开可回到工作室继续对比，删除时本地成图一并清理。"}
              </p>
            </div>
            <div className="lib-side">
              <span className="lib-count">
                {(view === "wardrobe" ? wardrobe.length : archive.length).toString().padStart(2, "0")} 件
              </span>
              {view === "wardrobe" ? (
                <button
                  type="button"
                  className="lib-add"
                  onClick={() => wardrobeInput.current?.click()}
                  disabled={wardrobeBusy}
                >
                  {wardrobeBusy ? "入库中…" : "+ 添加单品"}
                </button>
              ) : (
                <button type="button" className="lib-add" onClick={() => go("studio")}>
                  去工作室 →
                </button>
              )}
            </div>
          </div>

          {view === "wardrobe" ? (
            wardrobe.length === 0 ? (
              <div className="lib-empty">
                <strong>衣柜还是空的</strong>
                <span>上传一张平铺图或穿着图，之后每次试穿都能从这里直接取用。</span>
                <button type="button" className="lib-add" onClick={() => wardrobeInput.current?.click()}>
                  添加第一件单品
                </button>
              </div>
            ) : (
              <div className="lib-grid">
                {wardrobe.map((item) => (
                  <figure className="look" key={item.id}>
                    <button
                      type="button"
                      className="look-frame"
                      onClick={() => selectFromWardrobe(item)}
                      title="在工作室试穿"
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={item.url} alt={item.name} />
                      <span className="look-hint">在工作室试穿</span>
                    </button>
                    <figcaption>
                      <div className="look-meta">
                        <strong>{item.name}</strong>
                        <small>
                          {TYPE_LABEL[item.cloth_type]} · {formatDay(item.created_at)}
                        </small>
                      </div>
                      <button
                        type="button"
                        className={`look-del${pendingDelete === item.id ? " is-armed" : ""}`}
                        onClick={() => void removeGarment(item)}
                        title="删除后本地原图也会被清掉"
                      >
                        {pendingDelete === item.id ? "确认删除" : "删除"}
                      </button>
                    </figcaption>
                  </figure>
                ))}
                <button
                  type="button"
                  className="look look--add"
                  onClick={() => wardrobeInput.current?.click()}
                  disabled={wardrobeBusy}
                >
                  <span className="plus">+</span>
                  <span>{wardrobeBusy ? "入库中…" : "添加单品"}</span>
                </button>
              </div>
            )
          ) : archive.length === 0 ? (
            <div className="lib-empty">
              <strong>还没有试穿记录</strong>
              <span>在工作室完成一次试穿，结果会自动收进档案。</span>
              <button type="button" className="lib-add" onClick={() => go("studio")}>
                去试一件
              </button>
            </div>
          ) : (
            <div className="lib-grid">
              {archive.map((item) => (
                <figure className="look" key={item.id}>
                  <button
                    type="button"
                    className="look-frame"
                    onClick={() => openArchiveItem(item)}
                    title="在工作室打开"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={item.result_url} alt={item.garment_name} />
                    <span className="look-hint">在工作室打开</span>
                  </button>
                  <figcaption>
                    <div className="look-meta">
                      <strong>{item.garment_name}</strong>
                      <small>
                        {TYPE_LABEL[item.cloth_type]} ·{" "}
                        {item.cost_seconds ? `${item.cost_seconds}s · ` : ""}
                        {formatDay(item.created_at)}
                      </small>
                    </div>
                    <button
                      type="button"
                      className={`look-del${pendingDelete === item.id ? " is-armed" : ""}`}
                      onClick={() => void removeArchive(item)}
                      title="删除后本地成图也会被清掉"
                    >
                      {pendingDelete === item.id ? "确认删除" : "删除"}
                    </button>
                  </figcaption>
                </figure>
              ))}
            </div>
          )}

          {libraryError ? <div className="lib-note">衣柜与档案暂时不可用：{libraryError}</div> : null}

          <input
            ref={wardrobeInput}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            hidden
            onChange={(event) => {
              void addToWardrobe(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </main>
      ) : null}

      {toast ? <div className="toast">{toast}</div> : null}
    </>
  );
}
