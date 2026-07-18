/* global loadPyodide, JSZip */
"use strict";

const PYODIDE_INDEX_URL = "https://cdn.jsdelivr.net/pyodide/v0.28.3/full/";
// Bump this whenever bridge.py/pylib/app.js change, so browsers that cached the
// previous version (fetch() responses aren't covered by the HTML <script> tag's
// own cache-busting query string) pick up the new code instead of silently
// running stale logic.
const ASSET_VERSION = "3";
function versioned(path) {
  return `${path}${path.includes("?") ? "&" : "?"}v=${ASSET_VERSION}`;
}
const PYLIB_FILES = [
  { src: "pylib/utilities.py", dest: "/home/pyodide/utilities.py" },
  { src: "pylib/page_manager.py", dest: "/home/pyodide/page_manager.py" },
  { src: "pylib/enums.py", dest: "/home/pyodide/enums.py" },
  { src: "pylib/size_convert.py", dest: "/home/pyodide/size_convert.py" },
  { src: "pylib/assets/layouts.json", dest: "/home/pyodide/assets/layouts.json" },
  { src: "pylib/assets/arial.ttf", dest: "/home/pyodide/assets/arial.ttf" },
];
const FRONT_DIR = "/home/pyodide/game/front";
const BACK_DIR = "/home/pyodide/game/back";
const DS_DIR = "/home/pyodide/game/double_sided";
const OFFSET_STORAGE_KEY = "pdfmaker_riftbound_offset_v1";

const generateBtn = document.getElementById("generate-btn");
const resultEl = document.getElementById("result");
const logEl = document.getElementById("log");
const form = document.getElementById("pdf-form");

let pyodide = null;
let py = {}; // bridge.py functions, filled in once loaded
let lastDownloadUrl = null;

function setStatus(text) {
  generateBtn.textContent = text;
}

function appendLog(line) {
  logEl.classList.add("visible");
  logEl.textContent += (logEl.textContent ? "\n" : "") + line;
  logEl.scrollTop = logEl.scrollHeight;
}

function clearLog() {
  logEl.textContent = "";
  logEl.classList.remove("visible");
}

function showResult(message, kind) {
  resultEl.textContent = message;
  resultEl.className = kind || "";
}

// ---------------------------------------------------------------------------
// Upload zones
// ---------------------------------------------------------------------------

function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function setupUploadZone(zoneId, inputId, listId, multiple) {
  const zone = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  const list = document.getElementById(listId);
  const files = new Map(); // name -> File

  function render() {
    list.innerHTML = "";
    for (const [name, file] of files) {
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = `${name} (${humanSize(file.size)})`;
      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.textContent = "Remove";
      removeBtn.addEventListener("click", () => {
        files.delete(name);
        render();
      });
      li.appendChild(label);
      li.appendChild(removeBtn);
      list.appendChild(li);
    }
  }

  function addFiles(fileList) {
    const incoming = Array.from(fileList).filter((f) => f.type.startsWith("image/") || f.name);
    if (!multiple) {
      files.clear();
      if (incoming.length > 0) {
        const f = incoming[incoming.length - 1];
        files.set(f.name, f);
      }
    } else {
      for (const f of incoming) files.set(f.name, f);
    }
    render();
  }

  input.addEventListener("change", () => {
    addFiles(input.files);
    input.value = "";
  });

  ["dragover", "dragenter"].forEach((evt) =>
    zone.addEventListener(evt, (e) => {
      e.preventDefault();
      zone.classList.add("dragover");
    })
  );
  ["dragleave", "dragend", "drop"].forEach((evt) =>
    zone.addEventListener(evt, () => zone.classList.remove("dragover"))
  );
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files);
  });
  zone.addEventListener("click", (e) => {
    // Avoid double-opening the file picker: <label for> already opens it natively,
    // and clicks on the input/remove buttons/file list shouldn't open it at all.
    if (e.target.closest("input, button, li, label")) return;
    input.click();
  });

  return files;
}

const frontFiles = setupUploadZone("zone-front", "input-front", "list-front", true);
const backFiles = setupUploadZone("zone-back", "input-back", "list-back", false);
const dsFiles = setupUploadZone("zone-ds", "input-ds", "list-ds", true);

// ---------------------------------------------------------------------------
// Layout option selects, populated from the same layouts.json the CLI uses
// ---------------------------------------------------------------------------

function addOption(select, value, label, selected) {
  const opt = document.createElement("option");
  opt.value = value;
  opt.textContent = label;
  if (selected) opt.selected = true;
  select.appendChild(opt);
}

async function populateLayoutOptions() {
  const res = await fetch(versioned("pylib/assets/layouts.json"));
  const layouts = await res.json();

  const cardSizeSelect = document.getElementById("card_size");
  const priorityCards = ["standard", "poker", "bridge"];
  const cardNames = Object.keys(layouts.card_sizes);
  const orderedCards = [
    ...priorityCards.filter((n) => cardNames.includes(n)),
    ...cardNames.filter((n) => !priorityCards.includes(n)).sort(),
  ];
  for (const name of orderedCards) {
    const def = layouts.card_sizes[name];
    const note = name === "standard" ? " — Riftbound size" : "";
    addOption(cardSizeSelect, name, `${name} (${def.width} × ${def.height})${note}`, name === "standard");
    if (def.aliases) {
      for (const alias of def.aliases) {
        addOption(cardSizeSelect, alias, `${alias} (alias of ${name})`, false);
      }
    }
  }

  const paperSizeSelect = document.getElementById("paper_size");
  const priorityPapers = ["letter", "tabloid", "a4", "a3", "arch_b"];
  const paperNames = Object.keys(layouts.paper_sizes);
  const orderedPapers = [
    ...priorityPapers.filter((n) => paperNames.includes(n)),
    ...paperNames.filter((n) => !priorityPapers.includes(n)).sort(),
  ];
  for (const name of orderedPapers) {
    const def = layouts.paper_sizes[name];
    addOption(paperSizeSelect, name, `${name} (${def.width} × ${def.height})`, name === "letter");
    if (def.aliases) {
      for (const alias of def.aliases) {
        addOption(paperSizeSelect, alias, `${alias} (alias of ${name})`, false);
      }
    }
  }

  const specialtySelect = document.getElementById("specialty");
  if (layouts.specialty_layouts) {
    for (const name of Object.keys(layouts.specialty_layouts).sort()) {
      addOption(specialtySelect, name, name, false);
    }
  }
}

// Specialty overrides card_size/paper_size/registration/borderless (mirrors the CLI's validation).
document.getElementById("specialty").addEventListener("change", (e) => {
  const overridden = e.target.value !== "";
  for (const id of ["card_size", "paper_size", "registration", "borderless"]) {
    document.getElementById(id).disabled = overridden;
  }
  // The CLI rejects --borderless combined with --specialty; don't submit a stale checked
  // state that the user can no longer see or change while the control is disabled.
  if (overridden) document.getElementById("borderless").checked = false;
});

// ---------------------------------------------------------------------------
// Calibration offset (mirrors offset_pdf.py's --save / create_pdf.py --load_offset)
// ---------------------------------------------------------------------------

function loadStoredOffset() {
  const raw = localStorage.getItem(OFFSET_STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function refreshOffsetStatus() {
  const stored = loadStoredOffset();
  const statusEl = document.getElementById("offset-status");
  if (stored) {
    statusEl.textContent = `Saved: x=${stored.x_offset}, y=${stored.y_offset}, angle=${stored.angle_offset}°`;
    document.getElementById("x_offset").value = stored.x_offset;
    document.getElementById("y_offset").value = stored.y_offset;
    document.getElementById("angle_offset").value = stored.angle_offset;
  } else {
    statusEl.textContent = "No calibration saved yet.";
  }
}

document.getElementById("save-offset-btn").addEventListener("click", async () => {
  if (!py.save_offset_web) {
    showResult("Python runtime is still loading, try again in a moment.", "error");
    return;
  }
  const x = document.getElementById("x_offset").value || 0;
  const y = document.getElementById("y_offset").value || 0;
  const angle = document.getElementById("angle_offset").value || 0;
  const json = py.save_offset_web(x, y, angle);
  localStorage.setItem(OFFSET_STORAGE_KEY, json);
  refreshOffsetStatus();
});

// ---------------------------------------------------------------------------
// Pyodide bootstrap
// ---------------------------------------------------------------------------

async function boot() {
  try {
    setStatus("Loading Python runtime…");
    pyodide = await loadPyodide({ indexURL: PYODIDE_INDEX_URL });

    setStatus("Loading image & PDF libraries…");
    await pyodide.loadPackage(["pydantic", "matplotlib", "Pillow", "micropip"], {
      messageCallback: (msg) => appendLog(msg),
    });

    setStatus("Installing remaining dependencies…");
    const micropip = pyodide.pyimport("micropip");
    await micropip.install(["natsort", "filetype"]);

    setStatus("Fetching card-layout engine…");
    pyodide.FS.mkdirTree("/home/pyodide/assets");
    for (const file of PYLIB_FILES) {
      const buf = new Uint8Array(await (await fetch(versioned(file.src))).arrayBuffer());
      pyodide.FS.writeFile(file.dest, buf);
    }

    const bridgeSrc = await (await fetch(versioned("bridge.py"))).text();
    pyodide.runPython(bridgeSrc);

    for (const name of [
      "reset_upload_dirs",
      "generate",
      "set_log_callback",
      "save_offset_web",
      "hydrate_offset_web",
    ]) {
      py[name] = pyodide.globals.get(name);
    }

    py.set_log_callback((msg) => appendLog(msg));

    const stored = loadStoredOffset();
    if (stored) py.hydrate_offset_web(JSON.stringify(stored));
    refreshOffsetStatus();

    setStatus("Generate PDF");
    generateBtn.disabled = false;
  } catch (err) {
    console.error(err);
    setStatus("Failed to load — see message below");
    showResult(
      `The in-browser Python runtime failed to load: ${err.message || err}. Check your network connection and reload the page.`,
      "error"
    );
  }
}

// ---------------------------------------------------------------------------
// Form submission
// ---------------------------------------------------------------------------

function fieldValue(id) {
  return document.getElementById(id).value;
}

function parseSkip(text) {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
    .map((s) => parseInt(s, 10))
    .filter((n) => Number.isInteger(n) && n >= 0);
}

function canvasToPngBytes(source, width, height) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(source, 0, 0);
  return new Promise((resolve, reject) => {
    canvas.toBlob(async (blob) => {
      if (!blob) {
        reject(new Error("canvas export failed"));
        return;
      }
      resolve(new Uint8Array(await blob.arrayBuffer()));
    }, "image/png");
  });
}

async function decodeViaImageBitmap(file) {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  try {
    return await canvasToPngBytes(bitmap, bitmap.width, bitmap.height);
  } finally {
    bitmap.close();
  }
}

// Some browsers (notably older Safari) support a format via <img>/HTMLImageElement
// decode even when createImageBitmap() rejects it, so this is tried as a second path.
async function decodeViaImgElement(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.decoding = "async";
    img.src = url;
    await img.decode();
    return await canvasToPngBytes(img, img.naturalWidth, img.naturalHeight);
  } finally {
    URL.revokeObjectURL(url);
  }
}

// The Pyodide build of Pillow is compiled without some codecs available to real
// browsers (notably AVIF). Prefer the browser's native image decoder(s) and hand
// Pillow a PNG instead, so it never has to decode the original bytes itself.
// This also bakes in EXIF orientation, matching what ImageOps.exif_transpose()
// would have done downstream.
async function prepareUploadBytes(file) {
  const stem = file.name.replace(/\.[^./\\]+$/, "");

  for (const decode of [decodeViaImageBitmap, decodeViaImgElement]) {
    try {
      const bytes = await decode(file);
      return { bytes, filename: `${stem}.png`, converted: true };
    } catch (err) {
      // Try the next decode path.
    }
  }

  // Neither browser decode path worked — pass the original bytes through and let
  // the in-browser Pillow build try directly (works for formats like TIFF/DDS/QOI
  // that browsers don't natively support but Pillow does). If Pillow can't read
  // it either, generation will fail with a clear per-file error later.
  const bytes = new Uint8Array(await file.arrayBuffer());
  return { bytes, filename: file.name, converted: false };
}

async function writeFileMapToFS(dir, fileMap) {
  for (const [name, file] of fileMap) {
    appendLog(`Preparing ${name}…`);
    const { bytes, filename, converted } = await prepareUploadBytes(file);
    if (!converted) {
      appendLog(`⚠ ${name}: your browser could not decode this image format, passing it through as-is — it may fail below.`);
    }
    const safeName = filename.replace(/[\\/]/g, "_");
    pyodide.FS.writeFile(`${dir}/${safeName}`, bytes);
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  if (!pyodide || !py.generate) {
    showResult("The Python runtime is still loading. Please wait a moment and try again.", "error");
    return;
  }

  if (frontFiles.size === 0) {
    showResult("Upload at least one front image before generating.", "error");
    return;
  }

  generateBtn.disabled = true;
  setStatus("Generating…");
  clearLog();
  showResult("", "");
  if (lastDownloadUrl) {
    URL.revokeObjectURL(lastDownloadUrl);
    lastDownloadUrl = null;
  }

  try {
    py.reset_upload_dirs();
    await writeFileMapToFS(FRONT_DIR, frontFiles);
    await writeFileMapToFS(BACK_DIR, backFiles);
    await writeFileMapToFS(DS_DIR, dsFiles);

    const outputFormat = fieldValue("output_format");
    const params = {
      card_size: fieldValue("card_size"),
      paper_size: fieldValue("paper_size"),
      specialty: fieldValue("specialty"),
      registration: fieldValue("registration"),
      registration_orientation: fieldValue("registration_orientation"),
      borderless: document.getElementById("borderless").checked,
      only_fronts: document.getElementById("only_fronts").checked,
      fit: fieldValue("fit"),
      fit_backs: fieldValue("fit_backs"),
      crop: fieldValue("crop"),
      crop_backs: fieldValue("crop_backs"),
      extend_edges: fieldValue("extend_edges"),
      extend_edges_backs: fieldValue("extend_edges_backs"),
      extend_corners: fieldValue("extend_corners"),
      extend_corners_backs: fieldValue("extend_corners_backs"),
      extend_bleed: fieldValue("extend_bleed"),
      extend_bleed_backs: fieldValue("extend_bleed_backs"),
      output_images: outputFormat === "images",
      ppi: parseInt(fieldValue("ppi"), 10) || 300,
      quality: parseInt(fieldValue("quality"), 10),
      skip: parseSkip(fieldValue("skip")),
      load_offset: document.getElementById("load_offset").checked,
      label: fieldValue("label"),
      show_outline: document.getElementById("show_outline").checked,
    };

    const resultJson = py.generate(JSON.stringify(params));
    const result = JSON.parse(resultJson);

    if (!result.ok) {
      showResult(`Error: ${result.error}`, "error");
      return;
    }

    if (result.output_kind === "pdf") {
      const bytes = pyodide.FS.readFile(result.output_path);
      const blob = new Blob([bytes], { type: "application/pdf" });
      lastDownloadUrl = URL.createObjectURL(blob);
      showResult("PDF generated successfully.", "success");
      const a = document.createElement("a");
      a.href = lastDownloadUrl;
      a.download = "game.pdf";
      a.className = "download-link";
      a.textContent = "Download game.pdf";
      resultEl.appendChild(a);
    } else {
      const zip = new JSZip();
      for (const filename of result.files) {
        const bytes = pyodide.FS.readFile(`${result.output_dir}/${filename}`);
        zip.file(filename, bytes);
      }
      const blob = await zip.generateAsync({ type: "blob" });
      lastDownloadUrl = URL.createObjectURL(blob);
      showResult(`Generated ${result.files.length} page image(s).`, "success");
      const a = document.createElement("a");
      a.href = lastDownloadUrl;
      a.download = "game_pages.zip";
      a.className = "download-link";
      a.textContent = "Download game_pages.zip";
      resultEl.appendChild(a);
    }
  } catch (err) {
    console.error(err);
    showResult(`Unexpected error: ${err.message || err}`, "error");
  } finally {
    generateBtn.disabled = false;
    setStatus("Generate PDF");
  }
});

populateLayoutOptions();
refreshOffsetStatus();
boot();
