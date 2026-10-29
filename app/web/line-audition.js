/* Audition the actual reading plan. Only Use this take changes the saved selection. */
const LineAudition = {
  trigger(line, row, data) {
    if (line.speaker === 'Scene break') return '';
    const why = data.manual_draft ? 'Save the speaker assignments first.'
      : !data.audition_enabled ? 'Enable character voices to audition script lines.'
      : line.speaker === 'Unassigned' ? 'Choose a speaker first.'
      : line.omitted ? 'This line is omitted or included in the previous spoken passage.' : '';
    return `<button type="button" class="btn small" data-line-audition="${row}" ${why ? 'disabled' : ''}
      title="${esc(why || 'Listen with the saved voice, emotion and spoken text, without generating the chapter.')}">${icon('play')} Audition line</button>`;
  },

  cards(takes, busy) {
    return takes.map((take, index) => `<section class="audition-take">
      <div class="row between"><b>${index ? 'Alternative' : 'Current take'}</b><span class="chip ${take.current ? 'ok' : ''}">${take.current ? 'Selected in chapter' : 'Not selected'}</span></div>
      <audio controls preload="metadata" src="${esc(take.url)}" aria-label="${index ? 'Alternative' : 'Current take'}"></audio>
      ${(take.warnings || []).map((text) => `<p class="small audition-warning">${esc(text)}</p>`).join('')}
      <button type="button" class="btn ${index ? 'primary' : ''} small" data-use-take="${index}" ${busy ? 'disabled' : ''}>${take.current ? 'Keep current take' : 'Use this take'}</button>
    </section>`).join('');
  },

  bind(volume, stem, data, refresh) {
    document.querySelectorAll('[data-line-audition]').forEach((button) => {
      button.onclick = () => this.open(volume, stem, data, +button.dataset.lineAudition, button, refresh);
    });
  },

  open(volume, stem, data, row, trigger, refresh) {
    const line = data.lines[row];
    const dialog = document.createElement('dialog');
    dialog.className = 'modal line-audition';
    dialog.setAttribute('aria-labelledby', 'line-audition-title');
    dialog.innerHTML = `<div class="row between"><h2 id="line-audition-title">Audition line</h2><button type="button" class="btn ghost small" data-close>Close</button></div>
      <p class="muted small">Compare the saved reading choices. Nothing is selected until you keep a take.</p>
      <div class="row" data-reading><span class="chip">${esc(line.read_as || line.speaker)}</span><span class="chip">${esc((data.emotions || []).find((e) => e.key === line.emotion)?.label || 'Neutral')}</span></div>
      <blockquote class="audition-text" data-reading-text>${esc(line.spoken_text || line.text)}</blockquote>
      <p class="small muted audition-status" data-status aria-live="polite">Preparing the current take…</p>
      <p class="small audition-error" data-error role="alert" hidden></p>
      <div class="audition-takes" data-takes></div>
      <div class="row end"><button type="button" class="btn" data-compare disabled>Compare another take</button><button type="button" class="btn" data-retry hidden>Try preview again</button></div>
      <p class="small muted">This selects a passage take, not a new character voice. Generate chapter afterwards to assemble the updated audio.</p>`;
    const find = (selector) => dialog.querySelector(selector);
    const stopAudio = () => dialog.querySelectorAll('audio').forEach((audio) => audio.pause());
    let busy = false, takes = [], nextVariant = line.variant || 0;
    const request = (variant) => ({volume, stem, row, source_hash: data.source_hash,
      script_revision: data.script_revision, variant});
    const render = () => {
      stopAudio();
      find('[data-takes]').innerHTML = this.cards(takes, busy);
      find('[data-compare]').disabled = busy || !takes.length;
      find('[data-retry]').disabled = busy;
      dialog.querySelectorAll('[data-use-take]').forEach((button) => {
        button.onclick = async () => {
          busy = true;
          dialog.querySelectorAll('[data-use-take], [data-compare]').forEach((b) => { b.disabled = true; });
          find('[data-status]').textContent = 'Keeping the selected take…';
          try {
            await api('/api/chapter/audition/apply', {method: 'PUT', body: {token: takes[+button.dataset.useTake].token}});
            dialog.close();
            toast('Take kept. Generate chapter to assemble it; this preview audio will be reused.');
            await refresh(row);
          } catch (error) {
            if (dialog.isConnected) {
              find('[data-error]').hidden = false;
              find('[data-error]').textContent = error.message;
              find('[data-status]').textContent = 'The saved selection was not changed.';
              busy = false;
              render();
            }
          }
        };
      });
      dialog.querySelectorAll('audio').forEach((audio) => audio.addEventListener('play', () => {
        dialog.querySelectorAll('audio').forEach((other) => { if (other !== audio) other.pause(); });
      }));
    };
    const load = async (variant, slot) => {
      busy = true;
      find('[data-error]').hidden = true;
      find('[data-retry]').hidden = true;
      find('[data-status]').textContent = slot ? 'Generating an alternative with the same reading choices…' : 'Preparing the current take…';
      render();
      try {
        const take = await api('/api/chapter/audition', {method: 'POST', body: request(variant)});
        if (!dialog.isConnected) return;
        takes[slot] = take;
        nextVariant = take.variant;
        find('[data-reading]').innerHTML = `<span class="chip">${esc(take.read_as)}</span><span class="chip">${esc(take.emotion)}</span>`;
        find('[data-reading-text]').textContent = take.text;
        find('[data-status]').textContent = 'Ready. Play either take, then keep the one you prefer.';
      } catch (error) {
        if (!dialog.isConnected) return;
        find('[data-error]').hidden = false;
        find('[data-error]').textContent = error.message;
        find('[data-status]').textContent = 'The saved selection was not changed.';
        find('[data-retry]').hidden = takes.length > 0;
      } finally {
        if (dialog.isConnected) { busy = false; render(); }
      }
    };
    find('[data-close]').onclick = () => dialog.close();
    dialog.addEventListener('close', () => { stopAudio(); dialog.remove(); trigger?.focus({preventScroll: true}); });
    dialog.addEventListener('click', (event) => {
      if (event.target !== dialog) return;
      const box = dialog.getBoundingClientRect();
      if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
    });
    find('[data-compare]').onclick = () => load(nextVariant + 1, 1);
    find('[data-retry]').onclick = () => load(line.variant || 0, 0);
    document.body.append(dialog);
    dialog.showModal();
    load(nextVariant, 0);
  },
};
