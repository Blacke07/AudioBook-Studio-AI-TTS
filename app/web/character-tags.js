/* Name tags are the existing aliases and contextual display labels, attached to one canonical identity. */
const CharacterTags = {
  summary(name,state) {
    const entry=state.document.characters.find(c=>c.name===name),meta=state.document.organization.characters[name];
    return (entry?.aliases||[]).map(alias=>`<span class="chip" title="${esc(this.scope(alias,meta,state))}">${esc(alias)}</span>`).join('')||'<span class="small muted">No alternative names</span>';
  },
  scope(alias,meta,state) {
    const scope=Object.entries(meta.alias_scopes||{}).find(([name])=>name.toLowerCase()===alias.toLowerCase())?.[1]||{};
    const contexts=state.document.organization.contexts||[];
    const volumes=(scope.volumes||[]).map(id=>state.volumes.find(v=>v.id===id)?.name||'Missing volume');
    const details=(scope.contexts||[]).map(id=>{
      const c=contexts.find(item=>item.id===id),bounds=c?.chapter_range;
      return bounds ? [bounds.from?`From ${bounds.from}`:'From the start',bounds.before?`before ${bounds.before}`:'to the end'].join(' · '):c?.name||'Missing context';
    });
    return [...(volumes.length?volumes:['All volumes']),...details].join(' — ');
  },
  async editor(name) {
    const state=await api('/api/character-registry');
    const character=state.document.characters.find(c=>c.name===name),meta=state.document.organization.characters[name];
    if(!character||!meta)throw new Error('This character no longer exists.');
    const aliases=character.aliases||[];
    const pending=modal(`Name tags · ${name}`,`<p><b>Canonical identity:</b> ${esc(name)}<br><b>Default display name:</b> ${esc(meta.label)}</p>
      <p class="small muted">Tags recognize the same person; they do not create voices. Chapter rules can show a pseudonym before a reveal while preserving the canonical identity. Existing analyzed chapters are not reassigned automatically.</p>
      <div class="name-tag-list">${aliases.map((alias,i)=>`<div class="name-tag-row"><div><b>${esc(alias)}</b><p class="small muted">${esc(this.scope(alias,meta,state))}${(meta.labels||[]).some(l=>l.label===alias)?' · Display name':''}</p></div><button type="button" class="btn small" data-tag-edit="${i}">Edit tag</button></div>`).join('')||'<p class="muted">No name tags yet.</p>'}</div>`,
      [{label:'Close',value:null},{label:'Default display name…',value:'default'},{label:'Add name tag',value:'add',primary:true}]);
    const root=document.querySelector('.overlay:last-child .modal');root.classList.add('wide');
    let chosen=null;
    $$('[data-tag-edit]',root).forEach(button=>button.onclick=()=>{chosen=aliases[Number(button.dataset.tagEdit)];root.querySelector('[data-i="0"]').click();});
    const action=await pending;
    if(action==='default'){
      const form=await modal('Default display name',`<p>Identity stays <b>${esc(name)}</b>. This is the fallback outside contextual name tags.</p><label class="field"><span>Default name</span><input type="text" name="label" value="${esc(meta.label)}"></label>`,
        [{label:'Cancel',value:null},{label:'Preview name change',value:'form',primary:true}]);
      if(!form)return;
      const document=structuredClone(state.document);document.organization.characters[name].label=form.label.trim();
      const report=await api('/api/character-registry/preview',{method:'POST',body:{revision:state.revision,document}});
      return this.apply(report,name);
    }
    if(action==='add'||chosen)return this.edit(name,chosen,state);
  },
  async edit(name,alias,state) {
    const meta=state.document.organization.characters[name],org=state.document.organization;
    const scope=Object.entries(meta.alias_scopes||{}).find(([name])=>name.toLowerCase()===alias?.toLowerCase())?.[1]||{};
    const context=(scope.contexts||[]).length===1?org.contexts.find(c=>c.id===scope.contexts[0]):null;
    const volume=scope.volumes?.length===1?state.volumes.find(v=>v.id===scope.volumes[0])?.name||'':'';
    const advanced=(scope.contexts||[]).length>0&&!context?.chapter_range || (scope.volumes||[]).length>1;
    const pending=modal(alias?'Edit name tag':'New name tag',`<label class="field"><span>Alternative name</span><input type="text" name="alias" value="${esc(alias||'')}" maxlength="160"></label>
      ${advanced?`<p class="small muted">Current rule: ${esc(this.scope(alias,meta,state))}. Saving replaces this tag's existing scope with the rule below.</p>`:''}
      <label class="field"><span>Volume</span><select name="volume" id="tag-volume"><option value="">All volumes</option>${state.volumes.map(v=>`<option value="${esc(v.name)}" ${v.name===volume?'selected':''}>${esc(v.name)}</option>`).join('')}</select></label>
      <div class="split-preview"><label class="field"><span>From chapter (included)</span><select name="from" id="tag-from"></select></label><label class="field"><span>Before chapter (excluded)</span><select name="before" id="tag-before"></select></label></div>
      <label class="row"><input name="display" type="checkbox" ${(meta.labels||[]).some(l=>l.label===alias)?'checked':''}> Use this tag as the display name in this range</label>
      <p class="small muted">Gemma receives only the aliases valid in the chapter's context. Outside this range the default name remains. No source text or voice is changed.</p><p class="tag-error" role="alert" hidden></p>`,
      [{label:'Cancel',value:null},...(alias?[{label:'Remove tag',value:'delete'}]:[]),{label:'Preview tag rule',value:'form',primary:true}]);
    const root=document.querySelector('.overlay:last-child .modal');root.classList.add('wide');
    let loading=0;
    const update=async(initial=false)=>{
      const ticket=++loading,v=$('#tag-volume',root).value;
      const submit=root.querySelector(`[data-i="${alias?2:1}"]`);submit.disabled=true;
      for(const key of ['from','before']){$('#tag-'+key,root).innerHTML='<option value="">No chapter boundary</option>';$('#tag-'+key,root).disabled=true;}
      if(v){
        try{
          const data=await api('/api/character-registry/name-tag-chapters?volume='+encodeURIComponent(v));
          if(ticket!==loading)return;
          for(const key of ['from','before']){
            const select=$('#tag-'+key,root),saved=initial?context?.chapter_range?.[key]||'':'';
            select.innerHTML='<option value="">No chapter boundary</option>'+data.chapters.map(stem=>`<option value="${esc(stem)}">${esc(stem)}</option>`).join('');
            if(saved&&!data.chapters.includes(saved))select.innerHTML+=`<option value="${esc(saved)}">Missing chapter: ${esc(saved)} — choose another</option>`;
            select.disabled=false;select.value=saved;
          }
        }catch(error){if(ticket===loading)toast(error.message,'bad');return;}
      }
      if(ticket===loading)submit.disabled=false;
    };
    $('#tag-volume',root).onchange=()=>update();await update(true);
    let report=null,busy=false;
    const preview=async(remove,event)=>{
      event.stopPropagation();if(busy)return;busy=true;
      const buttons=$$('[data-i]',root),error=$('.tag-error',root);error.hidden=true;
      buttons.forEach(button=>button.disabled=true);
      try{
        const form=Object.fromEntries($$('[name]',root).map(f=>[f.name,f.type==='checkbox'?f.checked:f.value]));
        const request=remove?{alias,delete:true}:{...form,alias:form.alias.trim()};
        report=await api('/api/character-registry/name-tag-preview',{method:'POST',body:{...request,name,original:alias||null,revision:state.revision}});
        buttons[0].disabled=false;buttons[0].click();
      }catch(failure){error.hidden=false;error.textContent=failure.message;}
      finally{busy=false;buttons.forEach(button=>button.disabled=false);}
    };
    root.querySelector(`[data-i="${alias?2:1}"]`).onclick=event=>preview(false,event);
    if(alias)root.querySelector('[data-i="1"]').onclick=event=>preview(true,event);
    await pending;if(report)await this.apply(report,name);
  },
  async apply(report,name) {
    if(!await CharacterRegistry.confirm(report,'Apply name tags'))return;
    await api('/api/character-registry',{method:'PUT',body:{request:report.request,plan_id:report.plan_id}});
    toast('Name tags saved. Voices and manuscript are unchanged.');await route();
    await this.editor(name);
  },
};
