/* An explicit recipe-creation step. Reading rules remain in the existing VoiceRules editor. */
const OwnVoice = {
  markup(character, speakers) {
    return `<form class="stack" data-own-voice-form>
      <div class="row between"><h2>Create own voice</h2><button type="button" class="btn ghost small" data-own-voice-cancel>Cancel</button></div>
      <p>Create an audition recipe for <b>${esc(character.name)}</b>. Current reading voice: <b>${esc(character.read_as || character.name)}</b>.</p>
      <p class="small muted">Your reading rules stay as they are. Audition and fix a reference, then choose when to use it in Reading voice.</p>
      <label class="field"><span>Voice model</span><select name="model"><option value="VoiceDesign">VoiceDesign — describe a voice</option><option value="CustomVoice">CustomVoice — built-in speaker</option></select></label>
      <label class="field" data-own-design><span>Voice description (English)</span><textarea name="design" rows="4" required placeholder="Describe the character's age, timbre, accent and speaking style."></textarea></label>
      <label class="field" data-own-custom hidden><span>Built-in speaker</span><select name="custom" disabled required><option value="">Choose a speaker</option>${Object.entries(speakers).map(([name, about]) => `<option value="${esc(name)}">${esc(name)} — ${esc(about)}</option>`).join('')}</select></label>
      <label class="field"><span>Seed (take number)</span><input type="number" name="seed" min="0" max="2147483647" step="1" required value="${esc(character.seed ?? 0)}" aria-label="Seed (take number)" aria-describedby="own-voice-seed-help"><small id="own-voice-seed-help">Keep this number to repeat an audition choice. It does not set voice similarity.</small></label>
      <p class="small own-voice-error" data-own-voice-error role="alert" hidden></p>
      <div class="row end"><button type="submit" class="btn primary">Create recipe</button></div>
    </form>`;
  },
  editor(character, speakers, revision, created) {
    const dialog = document.createElement('dialog');
    dialog.className = 'modal own-voice-dialog';
    dialog.setAttribute('aria-label', 'Create own voice');
    dialog.innerHTML = this.markup(character, speakers);
    const form = dialog.querySelector('form'), model = form.elements.namedItem('model');
    let busy = false;
    const sync = () => {
      const design = model.value === 'VoiceDesign';
      dialog.querySelector('[data-own-design]').hidden = !design;
      dialog.querySelector('[data-own-custom]').hidden = design;
      form.elements.namedItem('design').disabled = !design;
      form.elements.namedItem('custom').disabled = design;
    };
    model.onchange = sync;
    const cancel = dialog.querySelector('[data-own-voice-cancel]');
    cancel.onclick = () => { if (!busy) dialog.close(); };
    dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
    form.onsubmit = async event => {
      event.preventDefault();
      if (busy || !form.reportValidity()) return;
      const seed = Number(form.elements.namedItem('seed').value);
      if (!Number.isInteger(seed)) return;
      const error = dialog.querySelector('[data-own-voice-error]');
      error.hidden = true;
      busy = true;
      const submit = form.querySelector('[type="submit"]');
      submit.disabled = cancel.disabled = true;
      try {
        const result = await api('/api/characters/own-voice', {method:'POST', body:{role:character.name, revision,
          model:model.value, design:form.elements.namedItem('design').value,
          custom:form.elements.namedItem('custom').value, seed}});
        dialog.close();
        toast(`Own voice recipe created for ${character.name}. Reading rules are unchanged.`);
        try { await created(result); }
        catch (refreshError) { toast(`Recipe created. Reopen Characters to refresh: ${refreshError.message}`, 'bad'); }
      } catch (failure) {
        error.hidden = false;
        error.textContent = failure.message;
      } finally {
        busy = false;
        submit.disabled = cancel.disabled = false;
      }
    };
    const closed = new Promise(resolve => dialog.addEventListener('close', () => { dialog.remove(); resolve(); }, {once:true}));
    document.body.append(dialog);
    sync();
    dialog.showModal();
    return closed;
  },
};
