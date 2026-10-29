/* Identity, reading voice and name tags are available at the point of reviewing a chapter. */
const ChapterCast = {
  async editor(source, volume, stem, data, row = null) {
    const state = await api('/api/character-registry');
    const known = state.document.characters.some(c=>c.name===source);
    const scope = Number.isInteger(row) ? 'line' : 'chapter';
    const pending = modal(`Character and voice · ${source}`, `<p><b>Character:</b> ${esc(source)}. Identity and reading voice are separate choices.</p>
      ${CharacterPicker.markup(state,source)}
      <label class="field"><span>Replace this speaker in</span><select name="scope">${Number.isInteger(row)?'<option value="line">Only this line</option>':''}<option value="chapter">This chapter</option><option value="everywhere">All analyzed chapters</option></select></label>
      <p class="small muted">Replacement changes saved assignments only. It does not merge identities, attach a tag or generate audio. Use Link / merge when these are two names for the same person.</p>`,
      [{label:'Cancel',value:null},{label:'Reading voice…',value:'voice'},{label:'Name tags…',value:'tags'},
       {label:'Link / merge identity…',value:'link'},{label:'Preview character change',value:'form',primary:true}]);
    const root=document.querySelector('.overlay:last-child .modal'); root.classList.add('wide');
    root.querySelector('[name="scope"]').value=scope;
    root.querySelector('[data-i="2"]').disabled=!known;
    root.querySelector('[data-i="3"]').disabled=!known;
    if(source===UNASSIGNED)root.querySelector('[data-i="1"]').disabled=true;
    const dispose=CharacterPicker.bind(root,state);
    let result;
    try { result=await pending; } finally { dispose(); }
    if(!result)return;
    if(result==='voice')return VoiceRules.editor(source,{volume,stem,source_hash:data.source_hash,
      chapter_choice:data.voice_rules?.characters?.[source],
      ...(Number.isInteger(row)?{row,text:data.lines[row].text,line_choice:data.voice_rules?.lines?.find(e=>e.row===row)?.read_as}: {})});
    if(result==='tags')return CharacterTags.editor(source);
    if(result==='link')return this.link(source,state);
    if(!result.target||result.target===source){toast('Choose a different character, or use Reading voice.');return;}
    const report=await api('/api/character-registry/reassign-preview',{method:'POST',body:{source,target:result.target,scope:result.scope,
      volume,stem,row,source_hash:data.source_hash,script_revision:data.script_revision}});
    const accepted=await modal('Preview character replacement',`<p><b>${esc(source)} → ${esc(result.target)}</b>: ${report.lines} ${report.lines===1?'line':'lines'} in ${report.chapters.length} ${report.chapters.length===1?'chapter':'chapters'}.</p>
      <div class="voice-impact">${report.chapters.map(c=>`<p>${esc(c.volume)} · ${esc(c.chapter)} — ${c.lines} ${c.lines===1?'line':'lines'}; ${c.removed_voice_overrides} old line voice overrides removed.</p>`).join('')}</div>
      <p>These lines will use the target character's reading rules. Affected audio/video may need regeneration. Original text, identities and fixed recordings stay intact.</p>`,
      [{label:'Cancel',value:false},{label:'Apply character replacement',value:true,primary:true}]);
    if(!accepted)return;
    await api('/api/character-registry/reassign',{method:'PUT',body:{request:report.request,plan_id:report.plan_id}});
    toast('Character assignments saved.');await route();
  },
  async link(source,state) {
    const targets=state.document.characters.filter(c=>c.name!==source);
    const form=await modal('Link a name to one identity',`<p><b>${esc(source)}</b> will become an alias of the selected identity. Its saved assignments are merged everywhere. The target keeps its voice; the old recordings remain on disk.</p>
      <label class="field"><span>Canonical character</span><select name="target"><option value="">Choose a character</option>${targets.map(c=>`<option value="${esc(c.name)}">${esc(c.name)}</option>`).join('')}</select></label>
      <p class="small muted">After merging, set the alias's chapter range in Name tags. Do not merge two different people who merely share a role.</p>`,
      [{label:'Cancel',value:null},{label:'Preview identity merge',value:'form',primary:true}]);
    if(!form?.target)return;
    const report=await api('/api/character-registry/merge-preview',{method:'POST',body:{revision:state.revision,source,target:form.target,rename:false}});
    if(!await CharacterRegistry.confirm(report,'Merge identities'))return;
    await api('/api/character-registry/merge',{method:'PUT',body:{request:report.request,plan_id:report.plan_id}});
    toast('Identity linked. Review its name-tag range.');await route();await CharacterTags.editor(form.target);
  },
  bind(volume,stem,data) {
    $$('[data-legend-voice]').forEach(button=>button.onclick=e=>guard(()=>this.editor(button.dataset.legendVoice,volume,stem,data),e.currentTarget));
  },
};
