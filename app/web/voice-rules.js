"use strict";
/* One editor is shared by Characters, volume Cast, chapter legend and individual lines. */
const VoiceRules = {
  label(speaker, lines) {
    const voices = [...new Set(lines.filter(line => line.speaker === speaker).map(line => line.read_as || speaker))];
    return `${speaker} → ${voices.length > 1 ? 'Mixed voices' : voices[0] || speaker}`;
  },
  async editor(speaker, context = {}) {
    const data = await api('/api/voice-rules/cast');
    const name = data.characters.find(c => c.name === speaker);
    const initialText = context.text || '';
    const scopes = context.stem ? [['line','Only this line'],['chapter','Only this chapter'],['everywhere','Everywhere']] : [['everywhere','Everywhere']];
    const choices = scopes.filter(([scope]) => scope !== 'line' || Number.isInteger(context.row));
    const body = `<p>The speaker stays <b>${esc(speaker)}</b>. Choose whose voice reads the words.</p>
      <label class="field"><span>Apply to</span><select name="scope">${choices.map(([value,label]) => `<option value="${value}">${label}</option>`).join('')}</select></label>
      <label class="field"><span>Reading voice</span><select name="read_as"><option value="">Use broader rule / own voice</option>
        <option value="${esc(speaker)}">Own voice — ${esc(speaker)}</option>
        ${data.voices.filter(s => s !== speaker).map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('')}</select></label>
      <p class="small muted">Current general rule: ${esc(name?.read_as || speaker)}. Priority: line → chapter → character → category → own voice.
      Another character means their own voice; rules do not chain.</p>
      <details><summary>Compare own voice with the narrator</summary><p class="small muted">Audition only. This does not apply a rule or change a fixed voice.</p>
        <label class="field"><span>Same text for both voices (maximum 600 characters)</span><textarea id="voice-compare-text" maxlength="600" rows="3">${esc(initialText)}</textarea></label>
        <button class="btn" type="button" id="voice-compare">Compare voices</button><div id="voice-compare-results"></div></details>`;
    const pending = modal(`Reading voice · ${speaker}`, body,
      [{label:'Cancel',value:null},{label:'Preview change',value:'form',primary:true}]);
    const scopeField = document.querySelector('[name="scope"]');
    const voiceField = document.querySelector('[name="read_as"]');
    const updateChoice = () => { voiceField.value = scopeField.value === 'everywhere' ? (name?.explicit_read_as || '')
      : scopeField.value === 'chapter' ? context.chapter_choice || '' : context.line_choice || ''; };
    scopeField.onchange = updateChoice; updateChoice();
    $('#voice-compare').onclick = e => guard(async () => {
      const result = await api('/api/voice-rules/compare',{method:'POST',body:{speaker,text:$('#voice-compare-text').value}});
      $('#voice-compare-results').innerHTML = result.takes.map(t => `<label class="field"><span>${esc(t.label)}</span><audio controls src="${esc(t.url)}"></audio></label>`).join('');
    },e.currentTarget);
    const form = await pending;
    if (!form) return;
    const request = {...context, speaker, scope:form.scope, read_as:form.read_as || null};
    delete request.text; delete request.line_choice; delete request.chapter_choice;
    await this.preview(request);
  },
  async preview(request) {
    const report = await api('/api/voice-rules/preview',{method:'POST',body:request});
    const affected = report.chapters.filter(c => c.changed);
    const confirm = await modal('Preview reading-voice change', `<p><b>${report.lines}</b> matching lines across <b>${report.chapters.length}</b> chapters.</p>
      <p>${affected.length} chapter plans change. Existing audio/video becomes outdated only where the sound changes.</p>
      <div class="voice-impact">${report.chapters.map(c => `<p><b>${esc(c.volume)}${c.chapter ? ' · '+esc(c.chapter) : ''}</b><br>
      ${c.error ? esc(c.error) : `${c.changed ? 'Reading plan changes' : 'No sound change'} · ${c.tags_read.length} speech tags restored · ${c.tags_omitted.length} speech tags omitted`}</p>`).join('') || '<p>No analyzed chapters yet. The rule will apply when you prepare them.</p>'}</div>
      <p class="small muted">Source files and speaker names are preserved. No audio is generated now. Undo is available until these edited data change.</p>`,
      [{label:'Cancel',value:false},{label:'Apply voice rule',value:true,primary:true}]);
    if (confirm) {
      await api('/api/voice-rules/apply',{method:'PUT',body:{request:report.request,plan_id:report.plan_id}});
      toast('Reading voice saved.'); route();
    }
  },
  async undo() {
    if (await modal('Undo last voice rule','<p>Restore the settings and assignments from before the last voice-rule change? Later edits are protected.</p>',
      [{label:'Cancel',value:false},{label:'Undo voice rule',value:true,primary:true}])) {
      await api('/api/voice-rules/undo',{method:'DELETE'}); toast('Voice rule undone.'); route();
    }
  },
  castMarkup(data) {
    const sort = entries => [...entries].sort((a,b) => b.lines-a.lines || a.name.localeCompare(b.name));
    const changed = c => c.read_as !== c.name;
    const row = c => `<button class="btn cast-voice" type="button" data-cast-voice="${esc(c.name)}"><b>${esc(c.label || c.name)}${changed(c) ? ' → '+esc(c.read_as) : ''}</b><span class="small muted">${c.lines} ${c.lines === 1 ? 'line' : 'lines'} · ${c.chapters} ${c.chapters === 1 ? 'chapter' : 'chapters'}${c.status && c.status!=='approved'?' · '+esc(c.status):''}</span></button>${c.fixed || c.read_as !== c.name ? '' : fieldHelp('Voice to review','No own reference voice is fixed for this character. Review the reading rule: using the narrator may be intentional. Audition a reference if this character should use its own voice.','Review')}`;
    const group = (title,entries) => entries.length ? `<section class="cast-group"><h3>${title} (${entries.length})</h3><div class="cast-list">${sort(entries).map(c=>`<div class="cast-entry">${row(c)}</div>`).join('')}</div></section>` : '';
    const used = data.characters.filter(c=>c.lines>0), unused=data.characters.filter(c=>!c.lines);
    const count=data.characters.filter(changed).length;
    return `<div class="row between cast-heading"><h2>Cast and reading voices</h2><button class="btn small" id="undo-voice-rule" ${data.can_undo ? '' : 'disabled'}>Undo last voice change</button></div>
      <details id="cast-disclosure"><summary>${count} changed · ${data.characters.length-count} unchanged — Show cast</summary>
      <p class="small muted">Narrator → cast → analyze and review text → audio → video.</p>
      ${(data.categories || [{id:'uncategorized',name:'Uncategorized'}]).map(cat=>{const people=used.filter(c=>(c.category||'uncategorized')===cat.id);return people.length?`<details data-cast-category="${esc(cat.id)}"><summary>${esc(cat.name)} · ${people.length} characters · ${people.filter(c=>c.status && c.status!=='approved').length} to review</summary><div class="cast-list">${sort(people).map(c=>`<div class="cast-entry">${row(c)}</div>`).join('')}</div></details>`:'';}).join('')}
      ${unused.length ? `<details class="cast-unused"><summary>Not in this volume (${unused.length})</summary>${group('Changed',unused.filter(changed))}${group('Unchanged',unused.filter(c=>!changed(c)))}</details>` : ''}
      ${data.characters.length ? '' : '<p>Add characters or analyze text to discover the cast.</p>'}</details>`;
  },
  async mount(volume) {
    const holder = $('#volume-cast');
    const data = await api('/api/voice-rules/cast?volume='+encodeURIComponent(volume));
    if (!holder?.isConnected) return;
    holder.innerHTML = this.castMarkup(data);
    const disclosure = $('#cast-disclosure');
    const key='cast-open:'+volume;
    try { disclosure.open=localStorage.getItem(key)==='true'; } catch { /* Disclosure works without storage. */ }
    disclosure.ontoggle=()=>{try{localStorage.setItem(key,String(disclosure.open));}catch{/* Optional UI preference. */}};
    holder.querySelectorAll('[data-cast-category]').forEach(section=>{const savedKey=key+':'+section.dataset.castCategory;try{section.open=localStorage.getItem(savedKey)==='true';}catch{}section.ontoggle=()=>{try{localStorage.setItem(savedKey,String(section.open));}catch{}};});
    holder.querySelectorAll('[data-cast-voice]').forEach(button => button.onclick = e => guard(() => this.editor(button.dataset.castVoice),e.currentTarget));
    $('#undo-voice-rule').onclick = e => guard(() => this.undo(),e.currentTarget);
    bindFieldHelp(holder);
  },
  bindChapter(volume, stem, data) {
    const context = {volume,stem,source_hash:data.source_hash};
    $('[data-clear-voice-conflicts]')?.addEventListener('click',e => guard(() => this.preview({...context,scope:'clear_conflicts'}),e.currentTarget));
    $$('[data-voice-rule]').forEach(button => button.onclick = e => {
      const index = +button.dataset.voiceRule;
      const line = data.lines[index];
      const selected = data.voice_rules?.lines?.find(entry => entry.row === index);
      guard(() => this.editor(line.speaker,{...context,row:index,text:line.text,line_choice:selected?.read_as,chapter_choice:data.voice_rules?.characters?.[line.speaker]}),e.currentTarget);
    });
    $$('[data-legend-voice]').forEach(button => button.onclick = e => guard(() => this.editor(button.dataset.legendVoice,{...context,chapter_choice:data.voice_rules?.characters?.[button.dataset.legendVoice],text:data.lines.find(line => line.speaker === button.dataset.legendVoice)?.text || ""}),e.currentTarget));
  }
};

async function editVolumeDialog(volume) {
  const pending = modal(`Edit volume · ${volume.name}`, `<p>Relink this volume to its active chapter folder. The stable name keeps its work and exports together.</p>
    <label class="field"><span>Volume name</span><input value="${esc(volume.name)}" readonly></label>
    <label class="field"><span>Chapter folder</span><div class="row"><input name="source" id="edit-volume-source" value="${esc(volume.source)}"><button class="btn" type="button" id="edit-volume-browse">Browse…</button></div></label>
    <p class="small muted">Changing the folder can make old assignments/audio outdated when chapter text differs. Source files and cached work are kept.</p>`,
    [{label:'Cancel',value:null},{label:'Save folder',value:'form',primary:true}]);
  $('#edit-volume-browse').onclick = e => guard(async () => {
    const result = await api('/api/pick-folder',{method:'POST'});
    if (result.path) $('#edit-volume-source').value = result.path;
  },e.currentTarget);
  const form = await pending;
  if (form) { await api('/api/volumes/'+encodeURIComponent(volume.name),{method:'PUT',body:form}); toast('Volume folder updated.'); route(); }
}

async function removeVolumeDialog(volume) {
  if (await modal(`Remove ${volume.name}?`, '<p>Remove this volume from the library? Its source chapters, generated audio and exported files stay on disk.</p>',
    [{label:'Cancel',value:false},{label:'Remove from library',value:true,primary:true}])) {
    await api('/api/volumes/'+encodeURIComponent(volume.name),{method:'DELETE'});
    location.hash = '#/'; route();
  }
}
