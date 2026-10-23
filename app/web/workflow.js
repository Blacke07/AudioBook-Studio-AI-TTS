"use strict";

/* Ordered chapter actions. Eligibility comes from the backend, which also checks it at execution. */
const ChapterWorkflow = (() => {
  let active = null;
  const close = () => {
    if (!active) return;
    active.panel.hidden = true;
    active.trigger.setAttribute("aria-expanded", "false");
    active.root.classList.remove("explained");
    active = null;
  };
  document.addEventListener("click", event => { if (active && !active.root.contains(event.target)) close(); });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && active) {
      const trigger = active.trigger;
      close();
      trigger.focus();
    }
  });
  window.addEventListener("resize", close);

  function html(chapters, volume) {
    const targets = selected.size ? chapters.filter(c => selected.has(c.stem)) : chapters;
    const textBlocked = targets.filter(c => !c.can_generate);
    const audioBlocked = targets.filter(c => !c.can_export);
    const errors = targets.filter(c => c.error);
    const review = targets.filter(c => c.unclear || c.state === "needs_review");
    const blocked = (items, instruction) => items.length
      ? `${instruction} (${items.length} ${items.length === 1 ? "chapter" : "chapters"}). ` + items.slice(0, 3).map(c =>
        `<a href="#/chapter/${encodeURIComponent(volume)}/${encodeURIComponent(c.stem)}">${esc(c.title)}</a>`).join(", ") + (items.length > 3 ? "…" : "")
      : "";
    const disabled = (items, instruction) => !targets.length || items.length ? `disabled title="${esc(instruction)}"` : "";
    const action = (id, label, symbol, explanation, attrs = "") => `<div class="workflow-action"><button class="btn" id="${id}" ${attrs}>${icon(symbol)} ${label}</button><p class="workflow-explanation">${explanation}</p></div>`;
    const category = (key, number, label, symbol, actions, reason = "") => `<div class="workflow-category" data-workflow="${key}"><button type="button" class="btn workflow-trigger" aria-expanded="false" aria-controls="workflow-${key}"><span class="workflow-number">${number}</span>${icon(symbol)} ${label}<span class="workflow-chevron" aria-hidden="true">⌄</span></button><div class="workflow-dropdown" id="workflow-${key}" hidden>${actions}${reason ? `<p class="workflow-explanation workflow-blocker">${reason}</p>` : ""}</div></div>`;
    const fallback = targets.some(c => c.narrator_fallback)
      ? `<p class="workflow-hint">Your Reading policy explicitly allows the narrator to read unassigned dialogue. Choose “Wait for my review” in Settings to require speaker assignments first.</p>` : "";
    return `<div class="workflow-categories" aria-label="Ordered chapter workflow">` +
      category("text", 1, "Text", "book",
        action("run-analyze", "Analyze Text", "wand", "Analyze or reanalyze this batch to identify speakers. Confirmation is required before replacing existing assignments.") +
        action("review-text", "Review speakers", "flag", "Open the chapters that still need speaker assignments.", review.length ? "" : "disabled") +
        action("diagnose-text", "Diagnose / repair", "info", "Explain errors and choose a repair. No voices or text are changed silently.", errors.length ? "" : "disabled")) +
      category("audio", 2, "Audio", "sound",
        action("run-render", "Generate audio", "play", "Use the approved speaker assignments and voices for this batch.", disabled(textBlocked, "Finish text analysis and speaker review for every chapter in this batch.")) +
        action("run-export", "Export chapter audio", "download", "Save one audio file per chapter in your selected export format.", disabled(audioBlocked, "Generate current audio for every chapter in this batch.")),
        blocked(textBlocked, "Finish text analysis and speaker review first") || blocked(audioBlocked, "Audio export waits for current audio")) +
      category("video", 3, "Video", "video",
        action("run-video", "Create chapter videos", "video", "Create MP4 videos from the existing, current chapter audio. Voices are not regenerated.", disabled(audioBlocked, "Generate current audio for every chapter in this batch.")) +
        action("youtube", "YouTube chapter timestamps", "list", "Save timestamps for joining the current chapter videos in volume order.", disabled(targets.filter(c => c.video.state !== "ready"), "Create current videos for every chapter in this batch.")),
        blocked(audioBlocked, "Generate current audio first")) + `</div><p class="workflow-hint">Hover for actions · Click a category for explanations</p>${fallback}`;
  }

  function bind() {
    close();
    document.querySelectorAll("[data-workflow]").forEach(root => {
      const trigger = root.querySelector(".workflow-trigger"), panel = root.querySelector(".workflow-dropdown");
      const open = pinned => {
        if (active?.root !== root) close();
        active = {root, trigger, panel, pinned};
        panel.hidden = false;
        panel.style.maxHeight = `${Math.max(80, window.innerHeight - trigger.getBoundingClientRect().bottom - 12)}px`;
        trigger.setAttribute("aria-expanded", "true");
        root.classList.toggle("explained", pinned);
      };
      root.onpointerenter = event => { if (event.pointerType === "mouse" && !active?.pinned) open(false); };
      root.onpointerleave = () => { if (active?.root === root && !active.pinned) close(); };
      root.onfocusout = event => { if (!root.contains(event.relatedTarget) && active?.root === root && !active.pinned) close(); };
      trigger.onclick = () => { if (active?.root === root && active.pinned) close(); else open(true); };
      trigger.onkeydown = event => {
        if (event.key === "ArrowDown") {
          event.preventDefault(); open(true); panel.querySelector("button:not(:disabled)")?.focus();
        }
      };
    });
  }

  async function diagnose(volume, stem) {
    const data = await api(`/api/chapter?volume=${encodeURIComponent(volume)}&stem=${encodeURIComponent(stem)}`);
    const c = data.chapter, issue = c.analysis_problem;
    const body = `<p><b>${esc(c.title)}</b></p><div class="diagnostic-error">${esc(c.error || "This chapter has no current error.")}</div>` +
      (issue ? `<p>${esc(issue.explanation)}</p>${issue.expected_count != null ? `<p>Batch ${esc(issue.batch)} of ${esc(issue.batches)}: ${esc(issue.returned_count ?? "no valid")} assignments returned; ${esc(issue.expected_count)} required.${issue.missing_rows?.length ? ` Missing row numbers: ${esc(issue.missing_rows.join(", "))}.` : ""}</p>` : `<p class="muted small">No matching batch details were recorded for this text. A new failed attempt will include them.</p>`}<p><b>Smaller batches:</b> ${esc(issue.repair)}</p><p><b>Manual review:</b> ${esc(issue.manual)}</p><p class="small muted">A successful repair replaces this chapter's speaker assignments. Your source text, voices and audio files are kept.</p>` : `<p>Open the chapter to review its working files and the original error. No automatic fix is available for this error type.</p>`);
    const choice = await modal("Chapter diagnosis", body, [
      {label:"Close", value:null}, {label:"Open chapter", value:"open"},
      ...(issue ? [{label:"Open manual editor", value:"manual"}, {label:"Repair analysis", value:"small_batches", primary:true}] : [])]);
    if (choice === "open" || choice === "manual") location.hash = `#/chapter/${encodeURIComponent(volume)}/${encodeURIComponent(stem)}`;
    if (choice !== "small_batches") return;
    if (data.lines.length && !await modal("Replace speaker assignments?", "<p>This chapter already has a script. A successful repair will replace its speaker assignments. A failed repair keeps the existing script.</p>", [{label:"Cancel",value:false}, {label:"Continue",value:true,primary:true}])) return;
    await api("/api/chapter/repair", {method:"POST",body:{volume,stem,mode:choice}});
    toast("Smaller-batch analysis queued. Review unresolved speakers when it finishes.");
    pollNow();
  }

  async function diagnoseBatch(volume, chapters) {
    if (chapters.length === 1) return diagnose(volume, chapters[0].stem);
    const stem = await modal("Choose a chapter to diagnose", "<p>Each error is handled separately; completed chapters are kept.</p>",
      [{label:"Cancel",value:null}, ...chapters.map(c => ({label:esc(c.stem),value:c.stem}))]);
    if (stem) await diagnose(volume, stem);
  }

  return {html, bind, diagnose, diagnoseBatch, isOpen: () => Boolean(active)};
})();
