"use strict";
/* One staged registry; Voice studio continues using the existing audition tools. */
const CharacterRegistry = {
  tab: 'quick', state: null, saved: '', selected: new Set(), query: '', filter: 'all', opened: new Set(['uncategorized']),
  dirty() { return this.state && JSON.stringify(this.state.document) !== this.saved; },
  async load() {
    this.state = await api('/api/character-registry');
    this.saved = JSON.stringify(this.state.document);
    this.selected.clear();
  },
  tabs() {
    return `<div class="row registry-tabs" role="tablist" aria-label="Character workspace"><button class="btn ${this.tab==='quick'?'primary':''}" role="tab" aria-selected="${this.tab==='quick'}" data-registry-tab="quick">Quick view</button><button class="btn ${this.tab==='studio'?'primary':''}" role="tab" aria-selected="${this.tab==='studio'}" data-registry-tab="studio">Voice studio</button></div>`;
  },
  bindTabs(root=view) {
    root.querySelectorAll('[data-registry-tab]').forEach((b,i,buttons)=>b.onkeydown=e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();const next=buttons[(i+1)%buttons.length];next.focus();next.click();}});
    root.querySelectorAll('[data-registry-tab]').forEach(b=>b.onclick=()=>guard(async()=>{
      if (this.dirty() && !await this.leave()) return;
      this.tab=b.dataset.registryTab; await viewCharacters();
    }));
  },
  studioHeader() {
    view.querySelector('.page-head').insertAdjacentHTML('afterend',this.tabs()); this.bindTabs();
  },
  async leave() {
    const choice=await modal('Unsaved character changes','<p>Apply your changes before leaving, or discard this draft?</p>',[{label:'Stay',value:null},{label:'Discard',value:'discard'},{label:'Preview changes',value:'apply',primary:true}]);
    if(choice==='discard'){await this.load();return true;}
    if(choice==='apply'){await this.apply();return !this.dirty();}
    return false;
  },
  async show() { if(!this.state || !this.dirty()) await this.load(); this.draw(); },
  options(items,current) { return items.map(([v,label])=>`<option value="${esc(v)}" ${v===current?'selected':''}>${esc(label)}</option>`).join(''); },
  voices(current,inherit=true,exclude='') {
    return this.options([...(inherit?[['','Inherit category']]:[]),['own','Own voice'],['Narrator','Narrator'],...this.state.document.characters.filter(c=>c.name!==exclude).map(c=>[c.name,c.name])],current);
  },
  readingInfo(c,cat) {
    const explicit=Object.hasOwn(c,'read_as'),target=explicit?c.read_as:(cat.voice==='own'?c.name:cat.voice);
    const origin=explicit?'Explicit choice':'Inherited from '+cat.name;
    return origin+' · '+(target==='Narrator'?'Narrator':this.state.fixed?.[target]?'Fixed reference':'No fixed reference');
  },
  draftChanged() {
    const pending=$('#registry-pending');
    if(pending){pending.hidden=!this.dirty();$('#registry-pending-count').textContent='Pending character changes';}
  },
  matches(c) {
    const m=this.state.document.organization.characters[c.name];
    return (this.filter==='all'||m.status===this.filter) && (!this.query||[c.name,m.label,...c.aliases].join(' ').toLowerCase().includes(this.query));
  },
  draw() {
    const doc=this.state.document,org=doc.organization;
    const categories=org.categories.map(c=>[c.id,c.name]);
    view.innerHTML=`<div class="page-head"><div><h1>Your characters</h1><p>Organize identities, review new speakers and choose whose voice reads them.</p></div><div class="row"><button class="btn" id="registry-import">Import characters</button><button class="btn" id="registry-categories">Manage categories</button><button class="btn primary" id="registry-new">${icon('plus')} New character</button></div></div>${this.tabs()}
      <div class="registry-tools"><label class="field"><span>Search names and aliases</span><input id="registry-query" value="${esc(this.query)}" type="text"></label><label class="field"><span>Show</span><select id="registry-filter">${this.options([['all','All'],['needs_review','Needs review'],['provisional','Provisional'],['approved','Approved']],this.filter)}</select></label><button class="btn" id="registry-move">Move selected (${this.selected.size})</button></div>
      <details class="registry-policy"><summary>Provisional character policy</summary><label class="row"><input id="registry-allow" type="checkbox" ${org.allow_provisional?'checked':''}> Allow provisional characters to use their assigned reading voice</label><p class="small muted">Uncertain speaker assignments still need review. This permits only named provisional identities with an available voice.</p></details>
      <div id="registry-pending" class="registry-pending" ${this.dirty()?'':'hidden'}><b id="registry-pending-count">Pending character changes</b><div class="row"><button class="btn" id="registry-discard">Discard</button><button class="btn primary" id="registry-apply">Preview and apply</button></div></div>
      ${org.categories.map(cat=>{
        const all=doc.characters.filter(c=>org.characters[c.name].category===cat.id),rows=all.filter(c=>this.matches(c));
        return `<details class="registry-category" data-category="${esc(cat.id)}" ${this.opened.has(cat.id)||this.query||this.filter!=='all'?'open':''}><summary><span class="registry-category-title">${esc(cat.name)}</span><span class="small muted">${all.length} ${all.length===1?'character':'characters'} · ${all.filter(c=>org.characters[c.name].status!=='approved').length} to review</span></summary><div class="row between"><button class="btn small" draggable="true" data-category-drag="${esc(cat.id)}" aria-label="Drag category ${esc(cat.name)}">${icon('list')} Reorder</button><details class="registry-actions"><summary class="btn small" aria-label="Category actions for ${esc(cat.name)}">Actions</summary><div class="registry-action-list">${['Edit category','Move up','Move down','Move characters…',...(cat.id!=='uncategorized'?['Delete category']:[])].map(action=>`<button class="btn" data-category-action="${esc(action)}" data-category-id="${esc(cat.id)}">${esc(action)}</button>`).join('')}</div></details></div>
        <div class="registry-table-wrap"><table class="registry-table"><thead><tr><th><input type="checkbox" data-select-group="${esc(cat.id)}" aria-label="Select all visible characters in ${esc(cat.name)}"></th><th>Character</th><th>Category</th><th>Reading voice</th><th>Status</th><th>Actions</th></tr></thead><tbody>${rows.map(c=>{
          const m=org.characters[c.name],explicit=Object.hasOwn(c,'read_as'),value=explicit?(c.read_as===c.name?'own':c.read_as):'';
          return `<tr data-character="${esc(c.name)}"><td><input type="checkbox" data-select-character ${this.selected.has(c.name)?'checked':''} aria-label="Select ${esc(m.label)}"><button class="btn ghost small" draggable="true" data-character-drag aria-label="Drag ${esc(m.label)}">${icon('list')}</button></td><td><strong>${esc(m.label)}</strong>${m.label!==c.name?`<span class="small muted">${esc(c.name)}</span>`:''}${m.scope?`<span class="small muted">${esc(m.scope)}</span>`:''}</td><td><select data-edit-category aria-label="Category for ${esc(m.label)}">${this.options(categories,m.category)}</select></td><td><select data-edit-voice aria-label="Reading voice for ${esc(m.label)}">${this.voices(value,true,c.name)}</select><span class="small muted">${esc(this.readingInfo(c,cat))}</span></td><td><select data-edit-status aria-label="Status for ${esc(m.label)}">${this.options([['approved','Approved'],['provisional','Provisional'],['needs_review','Needs review']],m.status)}</select></td><td><button class="btn small" data-listen-registry>Listen</button><button class="btn small" data-detail-registry>Details</button></td></tr>`;
        }).join('')||'<tr><td colspan="6" class="muted">No matching characters. Move characters here or change the filter.</td></tr>'}</tbody></table></div></details>`;
      }).join('')}`;
    this.bindTabs();
    $('#registry-query').oninput=e=>{this.query=e.target.value.toLowerCase();const position=e.target.selectionStart;clearTimeout(this.searchTimer);this.searchTimer=setTimeout(()=>{this.draw();$('#registry-query').focus();$('#registry-query').setSelectionRange(position,position);},180);};
    $('#registry-filter').onchange=e=>{this.filter=e.target.value;this.draw();};
    $('#registry-allow').onchange=e=>{org.allow_provisional=e.target.checked;this.draftChanged();};
    $('#registry-apply').onclick=e=>guard(()=>this.apply(),e.currentTarget);
    $('#registry-discard').onclick=()=>{this.state.document=JSON.parse(this.saved);this.draw();};
    $('#registry-categories').onclick=()=>guard(()=>this.manageCategories());
    $('#registry-move').onclick=()=>guard(()=>this.move([...this.selected]));
    $('#registry-import').onclick=()=>guard(()=>this.importCharacters());
    $('#registry-new').onclick=()=>guard(async()=>{if(this.dirty()&&!await this.leave())return;const form=await modal('New character','<label class="field"><span>Name</span><input name="name"></label><label class="field"><span>Gender</span><select name="gender"><option>unknown</option><option>female</option><option>male</option></select></label>',[{label:'Cancel',value:null},{label:'Add character',value:'form',primary:true}]);if(form){await api('/api/characters/new',{method:'POST',body:form});await this.load();this.draw();}});
    view.querySelectorAll('[data-category]').forEach(section=>{
      const id=section.dataset.category;
      section.ontoggle=()=>{section.open?this.opened.add(id):this.opened.delete(id);};
      section.ondragover=e=>{e.preventDefault();};
      section.ondrop=e=>{e.preventDefault();if(this.drag?.type==='character'){org.characters[this.drag.name].category=id;}else if(this.drag?.type==='category'){const from=org.categories.findIndex(c=>c.id===this.drag.id),to=org.categories.findIndex(c=>c.id===id);org.categories.splice(to,0,org.categories.splice(from,1)[0]);}this.drag=null;this.opened.add(id);this.draw();};
      const box=section.querySelector('[data-select-group]'),entries=doc.characters.filter(c=>org.characters[c.name].category===id&&this.matches(c));
      box.checked=entries.length>0&&entries.every(c=>this.selected.has(c.name));box.indeterminate=!box.checked&&entries.some(c=>this.selected.has(c.name));
      box.onchange=()=>{entries.forEach(c=>box.checked?this.selected.add(c.name):this.selected.delete(c.name));this.draw();};
    });
    view.querySelectorAll('[data-category-action]').forEach(b=>b.onclick=()=>guard(()=>this.categoryAction(b.dataset.categoryId,b.dataset.categoryAction)));
    view.querySelectorAll('.registry-actions').forEach(menu=>menu.onkeydown=e=>{if(e.key==='Escape'){menu.open=false;menu.querySelector('summary').focus();}});
    view.querySelectorAll('[data-category-drag]').forEach(b=>b.ondragstart=e=>{this.drag={type:'category',id:b.dataset.categoryDrag};e.dataTransfer.setData('text/plain',b.dataset.categoryDrag);});
    view.querySelectorAll('[data-character]').forEach(row=>{
      const name=row.dataset.character,c=doc.characters.find(c=>c.name===name),m=org.characters[name];
      row.querySelector('[data-character-drag]').ondragstart=e=>{this.drag={type:'character',name};e.dataTransfer.setData('text/plain',name);};
      row.querySelector('[data-select-character]').onchange=e=>{e.target.checked?this.selected.add(name):this.selected.delete(name);this.draw();};
      row.querySelector('[data-edit-category]').onchange=e=>{m.category=e.target.value;this.opened.add(m.category);this.draw();};
      row.querySelector('[data-edit-status]').onchange=e=>{m.status=e.target.value;this.draw();};
      row.querySelector('[data-edit-voice]').onchange=e=>{if(!e.target.value)delete c.read_as;else c.read_as=e.target.value==='own'?name:e.target.value;this.draw();};
      row.querySelector('[data-detail-registry]').onclick=()=>guard(()=>this.details(name));
      row.querySelector('[data-listen-registry]').onclick=e=>guard(async()=>{
        if(this.dirty()){toast('Apply reading-voice changes before listening.');return;}
        const target=this.state.reading[name]||name;
        if(target==='Narrator'){const narrator=await api('/api/settings');if(narrator.fixed?.url)await modal('Reading voice · Narrator',`<audio controls autoplay src="${esc(narrator.fixed.url)}"></audio>`);else toast('No narrator reference is fixed. Choose one on the Narrator page.');return;}
        const d=await api('/api/characters');const voice=d.characters.find(c=>c.name===target);
        if(!voice?.fixed){toast('No fixed reference is available. Choose a voice in Voice studio.');return;}
        await modal('Reading voice · '+target,`<audio controls autoplay src="${esc(voice.fixed.url)}"></audio>`);
      },e.currentTarget);
    });
  },
  async manageCategories() {
    const form=await modal('Manage categories',`<label class="field"><span>Category</span><select name="category"><option value="">New category</option>${this.options(this.state.document.organization.categories.map(c=>[c.id,c.name]),'')}</select></label><p>Edit a category here. Reorder and move characters using its Actions menu in Quick view.</p>`,[{label:'Cancel',value:null},{label:'Continue',value:'form',primary:true}]);
    if(form)await this.category(form.category||undefined);
  },
  async categoryAction(id,action) {
    const org=this.state.document.organization,cat=org.categories.find(c=>c.id===id);
    if(action==='Edit category')return this.category(id);
    if(action==='Move characters…')return this.move(Object.keys(org.characters).filter(n=>org.characters[n].category===id));
    if(action==='Delete category') {
      const dest=await this.chooseCategory('Move characters before deleting',id);if(!dest)return;
      Object.values(org.characters).filter(m=>m.category===id).forEach(m=>m.category=dest);
      org.categories=org.categories.filter(c=>c.id!==id);
    } else {
      const i=org.categories.indexOf(cat),j=i+(action==='Move up'?-1:1);
      if(j>=0&&j<org.categories.length)[org.categories[i],org.categories[j]]=[org.categories[j],org.categories[i]];
    }
    this.draw();
  },
  async category(id) {
    const org=this.state.document.organization,cat=org.categories.find(c=>c.id===id);
    const form=await modal(cat?'Edit category':'New category',`<label class="field"><span>Name</span><input name="name" maxlength="160" value="${esc(cat?.name||'')}"></label><label class="field"><span>Description for speaker detection</span><textarea name="description" maxlength="2000">${esc(cat?.description||'')}</textarea></label><label class="field"><span>Default reading voice</span><select name="voice">${this.voices(cat?.voice||'own',false)}</select></label>`,[{label:'Cancel',value:null},{label:'Save category',value:'form',primary:true}]);
    if(!form)return;
    if(!form.name.trim())throw new Error('Enter a category name.');
    if(cat)Object.assign(cat,form);else {const category={id:crypto.randomUUID(),...form};org.categories.push(category);this.opened.add(category.id);}
    this.draw();
  },
  async chooseCategory(title,exclude='') {
    return (await modal(title,`<label class="field"><span>Destination category</span><select name="category">${this.options(this.state.document.organization.categories.filter(c=>c.id!==exclude).map(c=>[c.id,c.name]),'')}</select></label><p>Explicit voice choices are preserved. Inherited voices may change; preview before applying.</p>`,[{label:'Cancel',value:null},{label:'Move',value:'form',primary:true}]))?.category;
  },
  async move(names){if(!names.length){toast('Select characters first.');return;}const id=await this.chooseCategory('Move '+names.length+' characters');if(id){names.forEach(n=>this.state.document.organization.characters[n].category=id);this.opened.add(id);this.draw();}},
  async details(name) {
    const doc=this.state.document,c=doc.characters.find(c=>c.name===name),m=doc.organization.characters[name];
    const form=await modal('Character details',`<p><b>${esc(name)}</b></p><label class="field"><span>Video label</span><input name="label" value="${esc(m.label)}"></label><label class="field"><span>Aliases (comma separated)</span><input name="aliases" value="${esc(c.aliases.join(', '))}"></label><label class="field"><span>Speaker detection context</span><textarea name="note">${esc(c.note)}</textarea></label><p class="small muted">${esc(m.reason)}${m.scope?' · Volume: '+esc(m.scope):''}</p>`,[{label:'Cancel',value:null},{label:'Review passages',value:'passages'},{label:'Rename identity',value:'rename'},{label:'Merge into…',value:'merge'},{label:'Save details',value:'form',primary:true}]);
    if(form==='passages')return this.passages(name);
    if(form==='merge')return this.merge(name);
    if(form==='rename')return this.merge(name,true);
    if(form){m.label=form.label;c.aliases=form.aliases.split(',').map(s=>s.trim()).filter(Boolean);c.note=form.note;this.draw();}
  },
  async passages(name){const d=await api('/api/character-registry/passages?name='+encodeURIComponent(name));await modal('Speaker passages',d.passages.map(p=>`<p><a href="#/chapter/${encodeURIComponent(p.volume)}/${encodeURIComponent(p.chapter)}">${esc(p.volume)} · ${esc(p.chapter)}</a><br>${esc(p.text)}</p>`).join('')||'<p>No saved passages yet.</p>');},
  async merge(source,rename=false){
    if(this.dirty()){toast('Apply or discard pending changes before merging.');return;}
    const form=await modal(rename?'Rename identity':'Merge character',`<p>${rename?'Rename '+esc(source)+' and keep its voice reference.':'Merge '+esc(source)+' into an existing identity. The target keeps its own voice.'} References remain on disk.</p><label class="field"><span>${rename?'New identity name (video label stays separate)':'Target character'}</span>${rename?'<input name="target">':`<select name="target">${this.options(this.state.document.characters.filter(c=>c.name!==source).map(c=>[c.name,c.name]),'')}</select>`}</label>`,[{label:'Cancel',value:null},{label:'Preview merge',value:'form',primary:true}]);
    if(!form)return;
    const report=await api('/api/character-registry/merge-preview',{method:'POST',body:{revision:this.state.revision,source,target:form.target,rename}});
    if(await this.confirm(report,'Apply merge')){await api('/api/character-registry/merge',{method:'PUT',body:{request:report.request,plan_id:report.plan_id}});await this.load();this.draw();}
  },
  async confirm(report,label='Apply changes') {
    return await modal('Preview character changes',`<p>${report.effects.length} affected chapter plans. Existing files remain available.</p><div class="voice-impact">${report.effects.map(e=>`<p><b>${esc(e.volume)} · ${esc(e.chapter)}</b><br>${esc(e.error|| (e.audio?'Audio and video need updating':'Video label changes; audio is reusable'))}</p>`).join('')||'<p>Organization only, or no analyzed chapters are affected.</p>'}</div>`,[{label:'Cancel',value:false},{label,value:true,primary:true}]);
  },
  async apply(){const report=await api('/api/character-registry/preview',{method:'POST',body:{revision:this.state.revision,document:this.state.document}});if(await this.confirm(report)){await api('/api/character-registry',{method:'PUT',body:{request:report.request,plan_id:report.plan_id}});await this.load();if(location.hash==='#/characters')this.draw();toast('Character registry saved.');}},
  async importCharacters(){
    const action=await modal('Import characters','<p>JSON imports names, aliases and recipes. It does not contain fixed reference recordings. Use a character and voice package to transfer those recordings.</p>',[{label:'Cancel',value:null},{label:'Character list — JSON',value:'json'},{label:'Character and voice package — .abstudio',value:'package',primary:true}]);
    if(action==='package'){if(this.dirty()&&!await this.leave())return;location.hash='#/project';return;}
    if(action!=='json')return;
    const input=document.createElement('input');input.type='file';input.accept='.json';
    input.onchange=()=>guard(async()=>{
      const file=input.files[0];if(!file)return;if(file.size>1024*1024*4)throw new Error('Character JSON must be under 4 MB.');
      const result=await api('/api/character-registry/import-preview',{method:'POST',body:{text:await file.text(),document:this.state.document}});
      this.state.document=result.document;
      this.draw();toast(`${result.added} characters added to the draft. Existing characters kept. Preview before applying; fixed recordings were not imported.`);
    });input.click();
  }
};
window.addEventListener('beforeunload',e=>{if(CharacterRegistry.dirty()){e.preventDefault();e.returnValue='';}});
