"use strict";
/* A category may carry one color from this palette; it marks the category wherever its characters are listed. */
const CATEGORY_COLORS = [['Blue', '#5b9bff'], ['Coral', '#ff8a5b'], ['Mint', '#5fd0a5'], ['Violet', '#b58cff'],
  ['Amber', '#f0a93b'], ['Teal', '#4fc3d9'], ['Magenta', '#e86aa6'], ['Pink', '#ffb3c7'], ['Lime', '#c8d85a'],
  ['Red', '#e5645f'], ['Brown', '#a98467'], ['Grey', '#9aa0a6']];
function categoryStyle(category) {
  return /^#[0-9a-f]{6}$/i.test(category?.color || '') ? ` style="--category-color:${category.color}"` : '';
}
/* One staged registry; Voice studio continues using the existing audition tools. */
const CharacterRegistry = {
  tab: 'quick', state: null, saved: '', selected: new Set(), query: '', filter: 'all', volumeFilter: 'all', drag: null, expandTimer: null, opened: new Set(['uncategorized']),
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
  async show() {
    if(!this.state || !this.dirty()) await this.load();
    const focus=sessionStorage.getItem('registryFocus');
    if(focus && this.state.document.organization.characters[focus]) this.opened.add(this.state.document.organization.characters[focus].category);
    this.draw();
    if(focus && this.state.document.organization.characters[focus]) {
      sessionStorage.removeItem('registryFocus');
      const row=view.querySelector(`tr[data-character="${focus.replace(/"/g,'\\"')}"]`);
      if(row){row.classList.add('highlighted');row.scrollIntoView({block:'center'});}
    }
  },
  options(items,current) { return items.map(([v,label])=>`<option value="${esc(v)}" ${v===current?'selected':''}>${esc(label)}</option>`).join(''); },
  voices(current,inherit=true,exclude='') {
    // Reading voices are voices: the characters' own and the shared ones, never a character without a voice.
    const voices=this.state.voices||this.state.document.characters.map(c=>c.name);
    return this.options([...(inherit?[['','Inherit category']]:[]),['own','Own voice'],['Narrator','Narrator'],...voices.filter(name=>name!==exclude).map(name=>[name,name])],current);
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
    if (this.volumeFilter!=='all') {
      const listed=m.volumes||[];
      if (listed.length && !listed.includes(this.volumeFilter)) return false;
    }
    return (this.filter==='all'||m.status===this.filter) && (!this.query||[c.name,m.label,...c.aliases].join(' ').toLowerCase().includes(this.query));
  },
  volumeName(id) {
    const volume=(this.state.volumes||[]).find(v=>v.id===id);
    return volume?volume.name:'Removed volume';
  },
  volumeChips(c,m) {
    const listed=m.volumes||[];
    const chips=listed.length?listed.map(id=>`<span class="chip volume-chip" title="${esc(this.volumeName(id))}">${esc(this.volumeName(id))}</span>`).join(''):'<span class="muted small">All volumes</span>';
    return `<button type="button" class="btn small volume-edit" data-volumes-edit="${esc(c.name)}" title="Edit volume membership">${chips}</button>`;
  },
  reorderable() {
    return this.volumeFilter==='all' && this.filter==='all' && !this.query;
  },
  async editVolumes(names,title) {
    const org=this.state.document.organization, volumes=this.state.volumes||[];
    if(!volumes.length){toast('Add a volume first.');return;}
    const current=names.length===1?new Set(org.characters[names[0]].volumes||[]):new Set();
    const body=`<p class="small muted">Choose where ${names.length===1?esc(org.characters[names[0]].label):'these characters'} appear. Membership organizes the cast; it never blocks analysis or generation. Clearing every box means “all volumes”.</p><div class="stack">${volumes.map((v,i)=>`<label class="row"><input type="checkbox" name="volume-${i}" ${current.has(v.id)?'checked':''}> ${esc(v.name)}</label>`).join('')}</div>`;
    const form=await modal(title,body,[{label:'Cancel',value:null},{label:'Save volumes',value:'form',primary:true}]);
    if(!form)return;
    const chosen=volumes.filter((v,i)=>form[`volume-${i}`]).map(v=>v.id);
    names.forEach(name=>{const m=org.characters[name];if(chosen.length)m.volumes=chosen;else delete m.volumes;});
    this.draftChanged();this.draw();
  },
  moveCharacter(name,delta) {
    const doc=this.state.document,org=doc.organization;
    const category=org.characters[name].category;
    const siblings=doc.characters.filter(c=>org.characters[c.name].category===category);
    const index=siblings.findIndex(c=>c.name===name),target=siblings[index+delta];
    if(!target)return;
    const a=doc.characters.findIndex(c=>c.name===name),b=doc.characters.findIndex(c=>c.name===target.name);
    [doc.characters[a],doc.characters[b]]=[doc.characters[b],doc.characters[a]];
    this.draw();toast('Order updated.');
  },
  clearDrag() {
    clearTimeout(this.expandTimer);
    this.drag=null;
    view.querySelectorAll('.drop-before,.drop-after,.drop-into').forEach(el=>el.classList.remove('drop-before','drop-after','drop-into'));
  },
  dropOnRow(row,event) {
    if(this.drag?.type!=='character')return;
    const doc=this.state.document,org=doc.organization;
    const source=this.drag.name,target=row.dataset.character;
    if(!target||source===target)return this.clearDrag();
    const rect=row.getBoundingClientRect(),after=event.clientY>rect.top+rect.height/2;
    const category=org.characters[target].category;
    const sourceEntry=doc.characters.find(c=>c.name===source);
    const removed=doc.characters.filter(c=>c.name!==source);
    const at=removed.findIndex(c=>c.name===target);
    org.characters[source].category=category;
    removed.splice(at+(after?1:0),0,sourceEntry);
    doc.characters=removed;
    this.opened.add(category);
    this.clearDrag();this.draw();toast('Order updated.');
  },
  dropOnCategory(section,event) {
    if(!this.drag)return;
    const doc=this.state.document,org=doc.organization,id=section.dataset.category;
    if(this.drag.type==='character') {
      const source=this.drag.name,removed=doc.characters.filter(c=>c.name!==source);
      const sourceEntry=doc.characters.find(c=>c.name===source);
      let at=-1;
      removed.forEach((c,index)=>{if(org.characters[c.name].category===id)at=index;});
      org.characters[source].category=id;
      removed.splice(at+1,0,sourceEntry);
      doc.characters=removed;
      this.opened.add(id);
    } else if(this.drag.type==='category') {
      const categories=org.categories;
      const from=categories.findIndex(c=>c.id===this.drag.id);
      if(from<0)return this.clearDrag();
      const dragged=categories.splice(from,1)[0];
      let to=categories.findIndex(c=>c.id===id);
      const rect=section.getBoundingClientRect();
      if(event.clientY>rect.top+rect.height/2)to+=1;
      categories.splice(Math.max(0,to),0,dragged);
    }
    const kind=this.drag?.type;
    this.clearDrag();this.draw();toast(kind==='category'?'Category order updated.':'Character moved.');
  },
  bindActions() {
    view.querySelectorAll('.registry-actions').forEach(menu=>{
      const summary=menu.querySelector('summary');
      let timer;
      menu.onpointerenter=()=>{clearTimeout(timer);menu.open=true;menu.dataset.hover='1';};
      menu.onpointerleave=()=>{if(menu.dataset.pinned==='1')return;timer=setTimeout(()=>{if(menu.dataset.pinned!=='1'){menu.open=false;menu.dataset.hover='';}},220);};
      summary.addEventListener('click',event=>{
        if(menu.dataset.pinned==='1'){menu.dataset.pinned='';menu.open=false;}
        else {event.preventDefault();menu.open=true;menu.dataset.pinned='1';menu.dataset.hover='';}
      });
      summary.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){setTimeout(()=>{menu.dataset.pinned=menu.open?'1':'';},0);}});
      menu.addEventListener('keydown',event=>{if(event.key==='Escape'){menu.open=false;summary.focus();}});
    });
  },
  rowMenu: null, rowTimer: null, rowCloseTimer: null,
  closeRowMenu() {
    clearTimeout(this.rowTimer);
    clearTimeout(this.rowCloseTimer);
    if(!this.rowMenu)return;
    const {menu,button}=this.rowMenu;
    menu.remove();
    button?.setAttribute('aria-expanded','false');
    this.rowMenu=null;
  },
  openRowMenu(button,name,pin=false) {
    this.closeRowMenu();
    const menu=document.createElement('div');
    menu.className='registry-action-list row-menu';
    menu.setAttribute('role','menu');
    menu.innerHTML=[['details','Details'],['up','Move up'],['down','Move down'],['category','Move to category…'],
      ['volumes','Assign to volumes…'],['listen','Listen']]
      .map(([action,label])=>`<button class="btn" role="menuitem" data-row-action="${action}">${label}</button>`).join('');
    document.body.append(menu);
    const rect=button.getBoundingClientRect();
    const height=menu.offsetHeight,width=menu.offsetWidth,margin=8;
    let top=rect.bottom+6;
    if(top+height>innerHeight-margin) top=rect.top-height-6;
    top=Math.min(Math.max(margin,top),Math.max(margin,innerHeight-height-margin));
    let right=innerWidth-rect.right;
    right=Math.min(Math.max(margin,right),Math.max(margin,innerWidth-width-margin));
    menu.style.top=top+'px';
    menu.style.right=right+'px';
    if(pin)menu.dataset.pinned='1';
    button.setAttribute('aria-expanded','true');
    this.rowMenu={menu,button,name};
    menu.querySelectorAll('[data-row-action]').forEach(item=>item.onclick=()=>guard(async()=>{
      const action=item.dataset.rowAction;
      this.closeRowMenu();
      await this.rowAction(name,action);
    }));
    menu.onpointerenter=()=>clearTimeout(this.rowCloseTimer);
    menu.onpointerleave=()=>{if(menu.dataset.pinned!=='1')this.rowCloseTimer=setTimeout(()=>this.closeRowMenu(),220);};
    menu.onkeydown=event=>{if(event.key==='Escape'){event.stopPropagation();this.closeRowMenu();button.focus();}};
  },
  async rowAction(name,action) {
    const meta=this.state.document.organization.characters[name],label=meta?.label||name;
    if(action==='details')return this.details(name);
    if(action==='up')return this.moveCharacter(name,-1);
    if(action==='down')return this.moveCharacter(name,1);
    if(action==='category'){const id=await this.chooseCategory('Move '+label);if(id){meta.category=id;this.opened.add(id);this.draftChanged();this.draw();}return;}
    if(action==='volumes')return this.editVolumes([name],`Volumes for ${label}`);
    if(action==='listen')return this.listen(name);
  },
  draw() {
    this.closeRowMenu();
    const doc=this.state.document,org=doc.organization;
    const categories=org.categories.map(c=>[c.id,c.name]);
    const volumeOptions=[['all','All volumes'],...(this.state.volumes||[]).map(v=>[v.id,v.name])];
    const backTo=sessionStorage.getItem('registryReturn');
    view.innerHTML=`<div class="page-head"><div><h1>Your characters</h1><p>Organize identities, review new speakers and choose whose voice reads them.</p></div><div class="row">${backTo?`<a class="btn" id="registry-back" href="${esc(backTo)}">Back to chapter</a>`:''}<button class="btn" id="registry-contexts">Contexts</button><button class="btn" id="registry-import">Import characters</button><button class="btn" id="registry-categories">Manage categories</button><button class="btn primary" id="registry-new">${icon('plus')} New character</button></div></div>${this.tabs()}
      <div class="registry-tools"><label class="field"><span>Search names and aliases</span><input id="registry-query" value="${esc(this.query)}" type="text"></label><label class="field"><span>Volume</span><select id="registry-volume">${this.options(volumeOptions,this.volumeFilter)}</select></label><label class="field"><span>Show</span><select id="registry-filter">${this.options([['all','All'],['needs_review','Needs review'],['provisional','Provisional'],['approved','Approved']],this.filter)}</select></label><button class="btn" id="registry-move">Move selected (${this.selected.size})</button><button class="btn" id="registry-assign-volumes">Assign to volumes…</button></div>
      <details class="registry-policy"><summary>Provisional character policy</summary><label class="row"><input id="registry-allow" type="checkbox" ${org.allow_provisional?'checked':''}> Allow provisional characters to use their assigned reading voice</label><p class="small muted">Uncertain speaker assignments still need review. This permits only named provisional identities with an available voice.</p><p class="small muted">Category order is presentation priority and helps choose a narrative context. It never decides who speaks; the text does.</p></details>
      <div id="registry-pending" class="registry-pending" ${this.dirty()?'':'hidden'}><b id="registry-pending-count">Pending character changes</b><div class="row"><button class="btn" id="registry-discard">Discard</button><button class="btn primary" id="registry-apply">Preview and apply</button></div></div>
      ${this.reorderable()?'':`<p class="small muted registry-filter-note">Drag reordering is off while a search or filter is active, so hidden characters never move. Use Actions for explicit moves.</p>`}
      ${org.categories.map((cat,position)=>{
        const all=doc.characters.filter(c=>org.characters[c.name].category===cat.id),rows=all.filter(c=>this.matches(c));
        return `<details class="registry-category"${categoryStyle(cat)} data-category="${esc(cat.id)}" ${this.opened.has(cat.id)||this.query||this.filter!=='all'||this.volumeFilter!=='all'?'open':''}><summary><span class="registry-category-title">${esc(cat.name)}</span><span class="small muted">Priority ${position+1} · ${all.length} ${all.length===1?'character':'characters'} · ${all.filter(c=>org.characters[c.name].status!=='approved').length} to review</span></summary><div class="row between"><button class="btn small" draggable="true" data-category-drag="${esc(cat.id)}" aria-label="Drag category ${esc(cat.name)}">${icon('list')} Reorder</button><details class="registry-actions"><summary class="btn small" aria-label="Category actions for ${esc(cat.name)}">Actions</summary><div class="registry-action-list">${['Edit category','Move up','Move down','Move characters…',...(cat.id!=='uncategorized'?['Delete category']:[])].map(action=>`<button class="btn" data-category-action="${esc(action)}" data-category-id="${esc(cat.id)}">${esc(action)}</button>`).join('')}</div></details></div>
        <div class="registry-table-wrap"><table class="registry-table"><thead><tr><th><input type="checkbox" data-select-group="${esc(cat.id)}" aria-label="Select all visible characters in ${esc(cat.name)}"></th><th>Character</th><th>Category</th><th>Volumes</th><th>Reading voice</th><th>Status</th><th>Actions</th></tr></thead><tbody>${rows.map(c=>{
          const m=org.characters[c.name],explicit=Object.hasOwn(c,'read_as'),value=explicit?(c.read_as===c.name?'own':c.read_as):'';
          return `<tr data-character="${esc(c.name)}" class="${this.selected.has(c.name)?'selected':''}"><td><input type="checkbox" data-select-character ${this.selected.has(c.name)?'checked':''} aria-label="Select ${esc(m.label)}"><button class="btn ghost small" draggable="${this.reorderable()}" data-character-drag aria-label="Drag ${esc(m.label)}">${icon('list')}</button></td><td><strong>${esc(m.label)}</strong>${m.label!==c.name?`<span class="small muted">${esc(c.name)}</span>`:''}${m.scope?`<span class="small muted">${esc(m.scope)}</span>`:''}</td><td><select data-edit-category aria-label="Category for ${esc(m.label)}">${this.options(categories,m.category)}</select></td><td>${this.volumeChips(c,m)}</td><td><select data-edit-voice aria-label="Reading voice for ${esc(m.label)}">${this.voices(value,true,c.name)}</select><span class="small muted">${esc(this.readingInfo(c,cat))}</span></td><td><select data-edit-status aria-label="Status for ${esc(m.label)}">${this.options([['approved','Approved'],['provisional','Provisional'],['needs_review','Needs review']],m.status)}</select></td><td class="row-actions-cell"><button type="button" class="btn small" data-row-menu="${esc(c.name)}" aria-haspopup="menu" aria-expanded="false">Actions</button></td></tr>`;
        }).join('')||'<tr><td colspan="7" class="muted">No matching characters. Move characters here or change the filter.</td></tr>'}</tbody></table></div></details>`;
      }).join('')}`;
    this.bindTabs();
    this.bindActions();
    $('#registry-back')?.addEventListener('click',()=>sessionStorage.removeItem('registryReturn'));
    $('#registry-query').oninput=e=>{this.query=e.target.value.toLowerCase();const position=e.target.selectionStart;clearTimeout(this.searchTimer);this.searchTimer=setTimeout(()=>{this.draw();$('#registry-query').focus();$('#registry-query').setSelectionRange(position,position);},180);};
    $('#registry-volume').onchange=e=>{this.volumeFilter=e.target.value;this.draw();};
    $('#registry-filter').onchange=e=>{this.filter=e.target.value;this.draw();};
    $('#registry-allow').onchange=e=>{org.allow_provisional=e.target.checked;this.draftChanged();};
    $('#registry-apply').onclick=e=>guard(()=>this.apply(),e.currentTarget);
    $('#registry-discard').onclick=()=>{this.state.document=JSON.parse(this.saved);this.draw();};
    $('#registry-categories').onclick=()=>guard(()=>this.manageCategories());
    $('#registry-contexts').onclick=()=>guard(()=>this.manageContexts());
    $('#registry-move').onclick=()=>guard(()=>this.move([...this.selected]));
    $('#registry-assign-volumes').onclick=()=>guard(()=>this.editVolumes([...this.selected],'Assign selected characters to volumes'));
    $('#registry-import').onclick=()=>guard(()=>this.importCharacters());
    $('#registry-new').onclick=()=>guard(async()=>{if(this.dirty()&&!await this.leave())return;const form=await modal('New character','<label class="field"><span>Name</span><input name="name"></label><label class="field"><span>Gender</span><select name="gender"><option>unknown</option><option>female</option><option>male</option></select></label>',[{label:'Cancel',value:null},{label:'Add character',value:'form',primary:true}]);if(form){await api('/api/characters/new',{method:'POST',body:form});await this.load();this.draw();}});
    view.querySelectorAll('[data-category]').forEach(section=>{
      const id=section.dataset.category;
      section.ontoggle=()=>{section.open?this.opened.add(id):this.opened.delete(id);};
      section.ondragover=e=>{if(!this.drag)return;e.preventDefault();if(e.dataTransfer)e.dataTransfer.dropEffect='move';
        if(this.drag.type==='character'&&!section.open){clearTimeout(this.expandTimer);this.expandTimer=setTimeout(()=>{section.open=true;this.opened.add(id);},550);}
        section.classList.add('drop-into');};
      section.ondragleave=e=>{if(!section.contains(e.relatedTarget)){section.classList.remove('drop-into');clearTimeout(this.expandTimer);}};
      section.ondrop=e=>{e.preventDefault();if(this.drag?.type==='category'&&this.drag.id===id)return this.clearDrag();this.dropOnCategory(section,e);};
      const box=section.querySelector('[data-select-group]'),entries=doc.characters.filter(c=>org.characters[c.name].category===id&&this.matches(c));
      box.checked=entries.length>0&&entries.every(c=>this.selected.has(c.name));box.indeterminate=!box.checked&&entries.some(c=>this.selected.has(c.name));
      box.onchange=()=>{entries.forEach(c=>box.checked?this.selected.add(c.name):this.selected.delete(c.name));this.draw();};
    });
    view.querySelectorAll('[data-category-action]').forEach(b=>b.onclick=()=>guard(()=>this.categoryAction(b.dataset.categoryId,b.dataset.categoryAction)));
    view.querySelectorAll('[data-category-drag]').forEach(b=>{b.ondragstart=e=>{this.drag={type:'category',id:b.dataset.categoryDrag};e.dataTransfer.setData('text/plain',b.dataset.categoryDrag);};});
    view.querySelectorAll('tr[data-character]').forEach(row=>{
      const name=row.dataset.character,c=doc.characters.find(c=>c.name===name),m=org.characters[name];
      row.querySelector('[data-character-drag]').ondragstart=e=>{if(!this.reorderable()){e.preventDefault();toast('Clear the search and filters before reordering.');return;}this.drag={type:'character',name};e.dataTransfer.setData('text/plain',name);row.classList.add('dragging');};
      row.ondragover=e=>{if(this.drag?.type!=='character')return;e.preventDefault();e.stopPropagation();view.querySelectorAll('tr.drop-before,tr.drop-after').forEach(other=>{if(other!==row)other.classList.remove('drop-before','drop-after');});const rect=row.getBoundingClientRect();const after=e.clientY>rect.top+rect.height/2;row.classList.toggle('drop-after',after);row.classList.toggle('drop-before',!after);};
      row.ondragleave=()=>row.classList.remove('drop-before','drop-after');
      row.ondrop=e=>{e.preventDefault();e.stopPropagation();this.dropOnRow(row,e);};
      row.querySelector('[data-select-character]').onchange=e=>{e.target.checked?this.selected.add(name):this.selected.delete(name);this.draw();};
      row.querySelector('[data-edit-category]').onchange=e=>{m.category=e.target.value;this.opened.add(m.category);this.draftChanged();this.draw();};
      row.querySelector('[data-edit-status]').onchange=e=>{m.status=e.target.value;this.draftChanged();this.draw();};
      row.querySelector('[data-edit-voice]').onchange=e=>{if(!e.target.value)delete c.read_as;else c.read_as=e.target.value==='own'?name:e.target.value;this.draftChanged();this.draw();};
      row.querySelector('[data-volumes-edit]').onclick=()=>guard(()=>this.editVolumes([name],`Volumes for ${m.label}`));
      const menuButton=row.querySelector('[data-row-menu]');
      menuButton.onpointerenter=()=>{clearTimeout(this.rowCloseTimer);if(this.rowMenu?.name===name)return;clearTimeout(this.rowTimer);this.rowTimer=setTimeout(()=>this.openRowMenu(menuButton,name),140);};
      menuButton.onpointerleave=()=>{clearTimeout(this.rowTimer);if(this.rowMenu?.name===name&&this.rowMenu.menu.dataset.pinned!=='1'){clearTimeout(this.rowCloseTimer);this.rowCloseTimer=setTimeout(()=>this.closeRowMenu(),200);}};
      menuButton.onclick=e=>{e.preventDefault();e.stopPropagation();if(this.rowMenu?.name===name){if(this.rowMenu.menu.dataset.pinned==='1')this.closeRowMenu();else this.rowMenu.menu.dataset.pinned='1';}else this.openRowMenu(menuButton,name,true);};
      menuButton.onkeydown=e=>{if(e.key==='Escape'){this.closeRowMenu();return;}if(e.key==='Enter'||e.key===' '||e.key==='ArrowDown'){e.preventDefault();this.openRowMenu(menuButton,name,true);this.rowMenu?.menu.querySelector('[data-row-action]')?.focus();}};
    });
    view.ondragend=()=>{view.querySelectorAll('.dragging').forEach(el=>el.classList.remove('dragging'));this.clearDrag();};
    view.querySelectorAll('[data-category]').forEach(section=>section.addEventListener('dragleave',e=>{if(!section.contains(e.relatedTarget))section.classList.remove('drop-into');}));
  },
  async listen(name) {
    if(this.dirty()){toast('Apply reading-voice changes before listening.');return;}
    const target=this.state.reading[name]||name;
    if(target==='Narrator'){const narrator=await api('/api/settings');if(narrator.fixed?.url)await modal('Reading voice · Narrator',`<audio controls autoplay src="${esc(narrator.fixed.url)}"></audio>`);else toast('No narrator reference is fixed. Choose one on the Narrator page.');return;}
    const data=await api('/api/characters');const voice=data.characters.find(c=>c.name===target);
    if(!voice?.fixed){toast('No fixed reference is available. Choose a voice in Voice studio.');return;}
    await modal('Reading voice · '+target,`<audio controls autoplay src="${esc(voice.fixed.url)}"></audio>`);
  },
  async manageContexts() {
    const contexts=this.state.document.organization.contexts||[];
    if(!contexts.length){toast('No narrative contexts yet. Create one from a chapter scene.');return;}
    const form=await modal('Narrative contexts',
      `<label class="field"><span>Context</span><select name="context">${contexts.map(c=>`<option value="${esc(c.id)}">${esc(c.name)} — ${esc(this.volumeName(c.volume))}</option>`).join('')}</select></label>
       <label class="field"><span>Action</span><select name="action"><option value="rename">Rename or describe</option><option value="delete">Delete context</option></select></label>
       <p class="small muted">Contexts scope aliases and video labels. Deleting one clears those references; it never changes chapter assignments.</p>`,
      [{label:'Cancel',value:null},{label:'Continue',value:'form',primary:true}]);
    if(!form)return;
    if(form.action==='delete'){
      const ok=await modal('Delete this context?',`<p>The context is removed from the registry and from every character alias scope and video label. Chapter speaker assignments stay as they are.</p>`,
        [{label:'Cancel',value:false},{label:'Delete context',value:true,primary:true}]);
      if(!ok)return;
      await api('/api/character-registry/contexts',{method:'POST',body:{action:'delete',id:form.context,revision:this.state.revision}});
      await this.load();this.draw();toast('Context deleted.');return;
    }
    const context=contexts.find(c=>c.id===form.context);
    const rename=await modal('Rename context',
      `<label class="field"><span>Name</span><input name="name" maxlength="160" value="${esc(context.name)}"></label>
       <label class="field"><span>Description</span><textarea name="description" maxlength="2000">${esc(context.description||'')}</textarea></label>`,
      [{label:'Cancel',value:null},{label:'Save context',value:'form',primary:true}]);
    if(!rename||!rename.name.trim())return;
    await api('/api/character-registry/contexts',{method:'POST',body:{action:'update',id:context.id,name:rename.name.trim(),description:rename.description||'',revision:this.state.revision}});
    await this.load();this.draw();toast('Context saved.');
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
    const form=await modal(cat?'Edit category':'New category',`<label class="field"><span>Name</span><input name="name" maxlength="160" value="${esc(cat?.name||'')}"></label><label class="field"><span>Description for speaker detection</span><textarea name="description" maxlength="2000">${esc(cat?.description||'')}</textarea></label><label class="field"><span>Default reading voice</span><select name="voice">${this.voices(cat?.voice||'own',false)}</select></label><label class="field"><span>Color</span><select name="color"><option value="">No color</option>${CATEGORY_COLORS.map(([label,value])=>`<option value="${value}" style="color:${value}" ${cat?.color?.toLowerCase()===value?'selected':''}>■ ${label}</option>`).join('')}</select></label>`,[{label:'Cancel',value:null},{label:'Save category',value:'form',primary:true}]);
    if(!form)return;
    if(!form.name.trim())throw new Error('Enter a category name.');
    const {color,...fields}=form;
    if(cat){Object.assign(cat,fields);if(color)cat.color=color;else delete cat.color;}
    else {const category={id:crypto.randomUUID(),...fields,...(color?{color}:{})};org.categories.push(category);this.opened.add(category.id);}
    this.draw();
  },
  async chooseCategory(title,exclude='') {
    return (await modal(title,`<label class="field"><span>Destination category</span><select name="category">${this.options(this.state.document.organization.categories.filter(c=>c.id!==exclude).map(c=>[c.id,c.name]),'')}</select></label><p>Explicit voice choices are preserved. Inherited voices may change; preview before applying.</p>`,[{label:'Cancel',value:null},{label:'Move',value:'form',primary:true}]))?.category;
  },
  async move(names){if(!names.length){toast('Select characters first.');return;}const id=await this.chooseCategory('Move '+names.length+' characters');if(id){names.forEach(n=>this.state.document.organization.characters[n].category=id);this.opened.add(id);this.draw();}},
  async details(name) {
    const doc=this.state.document,c=doc.characters.find(c=>c.name===name),m=doc.organization.characters[name];
    const contexts=doc.organization.contexts||[];
    const contextName=id=>contexts.find(item=>item.id===id)?.name||'Removed context';
    const contextLines=(m.labels||[]).filter(item=>(item.contexts||[]).length)
      .flatMap(item=>item.contexts.map(id=>`${contextName(id)} = ${item.label}`)).join('\n');
    const volumes=(m.volumes||[]).map(id=>this.volumeName(id));
    const form=await modal('Character details',`<p><b>${esc(name)}</b></p><label class="field"><span>Video label</span><input name="label" value="${esc(m.label)}"></label>
      <label class="field"><span>Contextual video labels (one per line: Context = Label)</span><textarea name="context_labels" rows="3" placeholder="Before the reveal = The soldier">${esc(contextLines)}</textarea></label>
      <label class="field"><span>Aliases (comma separated)</span><input name="aliases" value="${esc(c.aliases.join(', '))}"></label>
      <label class="field"><span>Speaker detection context</span><textarea name="note">${esc(c.note)}</textarea></label>
      <p class="small muted">${esc(m.reason)}${volumes.length?' · Volumes: '+esc(volumes.join(', ')):''}</p>`,
      [{label:'Cancel',value:null},{label:'Review passages',value:'passages'},{label:'Rename identity',value:'rename'},{label:'Merge into…',value:'merge'},{label:'Save details',value:'form',primary:true}]);
    if(form==='passages')return this.passages(name);
    if(form==='merge')return this.merge(name);
    if(form==='rename')return this.merge(name,true);
    if(form){
      const parsed=[], known=new Map(contexts.map(item=>[item.name.toLowerCase(),item.id]));
      for(const line of String(form.context_labels||'').split('\n')){
        const text=line.trim();if(!text)continue;
        const at=text.indexOf('=');if(at<1)throw new Error('Use “Context name = Label” on each line.');
        const context=known.get(text.slice(0,at).trim().toLowerCase()),label=text.slice(at+1).trim();
        if(!context)throw new Error('Unknown context: '+text.slice(0,at).trim());
        if(!label)continue;
        const existing=parsed.find(item=>item.label===label);
        if(existing)existing.contexts.push(context);else parsed.push({label,contexts:[context]});
      }
      const kept=(m.labels||[]).filter(item=>!(item.contexts||[]).length);
      const labels=[...kept,...parsed];
      if(labels.length)m.labels=labels;else delete m.labels;
      m.label=form.label;c.aliases=form.aliases.split(',').map(s=>s.trim()).filter(Boolean);c.note=form.note;this.draw();
    }
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
document.addEventListener('click',event=>{if(!event.target.closest('.registry-actions'))view.querySelectorAll('.registry-actions[open]').forEach(menu=>{menu.open=false;menu.dataset.pinned='';});if(!event.target.closest('.row-menu')&&!event.target.closest('[data-row-menu]'))CharacterRegistry.closeRowMenu();});
document.addEventListener('keydown',event=>{if(event.key==='Escape')CharacterRegistry.closeRowMenu();});
window.addEventListener('resize',()=>CharacterRegistry.closeRowMenu());
window.addEventListener('scroll',()=>CharacterRegistry.closeRowMenu(),true);
