/* Browse identities by the registry's category order; voice choices stay separate. */
const CharacterPicker = {
  groups(state) {
    const doc=state.document, org=doc.organization || {}, meta=org.characters || {};
    const groups=[{name:'Narration',characters:[{name:NARRATOR}]}];
    for(const category of org.categories || []) {
      const characters=doc.characters.filter(c=>meta[c.name]?.category===category.id);
      if(characters.length)groups.push({name:category.name,characters});
    }
    const ids=new Set((org.categories || []).map(c=>c.id));
    const remaining=doc.characters.filter(c=>!ids.has(meta[c.name]?.category));
    if(remaining.length)groups.push({name:'Uncategorized',characters:remaining});
    return groups;
  },
  markup(state, selected) {
    return `<div class="field character-picker"><span id="character-picker-label">Character</span>
      <button type="button" class="btn character-picker-trigger" aria-labelledby="character-picker-label character-picker-value" aria-expanded="false" aria-controls="character-picker-popup"><span id="character-picker-value">${esc(selected===UNASSIGNED?'Choose a character':selected)}</span><span aria-hidden="true">⌄</span></button>
      <input type="hidden" name="target" value="${esc(selected===UNASSIGNED?'':selected)}">
      <div id="character-picker-popup" class="character-picker-popup" hidden>
        <div class="character-picker-categories" role="group" aria-label="Character categories">${this.groups(state).map((g,i)=>`<button type="button" class="character-picker-category" data-category="${i}" aria-pressed="false"><span>${esc(g.name)}</span><small>${g.characters.length}</small><span aria-hidden="true">›</span></button>`).join('')}</div>
        <div class="character-picker-people" role="group" aria-label="Characters"></div>
      </div></div>`;
  },
  bind(root,state) {
    const field=root.querySelector('.character-picker'), overlay=root.closest('.overlay');
    const trigger=field.querySelector('.character-picker-trigger'), value=field.querySelector('[name="target"]');
    const label=field.querySelector('#character-picker-value'), popup=field.querySelector('.character-picker-popup');
    const people=popup.querySelector('.character-picker-people'), categories=[...popup.querySelectorAll('[data-category]')];
    const groups=this.groups(state); let active=0;
    // Keep the dropdown outside the scrolling modal so neither column is clipped.
    overlay.append(popup);
    const close=(focus=false)=>{popup.hidden=true;trigger.setAttribute('aria-expanded','false');if(focus)trigger.focus();};
    const show=index=>{
      active=index;
      categories.forEach((button,i)=>button.setAttribute('aria-pressed',String(i===index)));
      people.innerHTML=`<div class="character-picker-heading">${esc(groups[index].name)}</div>`+groups[index].characters.map((c,i)=>{
        const voice=state.reading?.[c.name] || c.name;
        return `<button type="button" class="character-picker-person" data-person="${i}" aria-pressed="${c.name===value.value}"><span><b>${esc(c.name)}</b><small>Reads as ${esc(voice)}</small></span><span class="character-picker-check" aria-hidden="true">${c.name===value.value?icon('check'):''}</span></button>`;
      }).join('');
      people.scrollTop=0;
      people.querySelectorAll('[data-person]').forEach(button=>button.onclick=()=>{
        const name=groups[active].characters[Number(button.dataset.person)].name;
        value.value=name;label.textContent=name;close(true);
      });
    };
    const open=()=>{
      const index=groups.findIndex(g=>g.characters.some(c=>c.name===value.value));show(index<0?0:index);
      popup.hidden=false;trigger.setAttribute('aria-expanded','true');
      const rect=trigger.getBoundingClientRect(), width=Math.min(Math.max(rect.width,600),window.innerWidth-32);
      popup.style.width=`${width}px`;popup.style.left=`${Math.max(16,Math.min(rect.left,window.innerWidth-width-16))}px`;
      const below=window.innerHeight-rect.bottom-16, above=rect.top-16;
      const height=Math.min(340,Math.max(below,above));popup.style.maxHeight=`${height}px`;
      popup.style.top=`${below>=Math.min(340,above)?rect.bottom+6:rect.top-height-6}px`;
    };
    trigger.onclick=()=>popup.hidden?open():close();
    trigger.onkeydown=event=>{if(event.key==='ArrowDown'){event.preventDefault();open();categories[active].focus();}};
    categories.forEach((button,index)=>{
      button.onmouseenter=()=>show(index);button.onfocus=()=>show(index);button.onclick=()=>show(index);
      button.onkeydown=event=>{
        if(event.key==='ArrowRight'){event.preventDefault();people.querySelector('[data-person]')?.focus();}
        if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();categories[(index+(event.key==='ArrowDown'?1:-1)+categories.length)%categories.length].focus();}
      };
    });
    people.onkeydown=event=>{
      const buttons=[...people.querySelectorAll('[data-person]')], index=buttons.indexOf(document.activeElement);
      if(event.key==='ArrowLeft'){event.preventDefault();categories[active].focus();}
      if(index>=0&&(event.key==='ArrowDown'||event.key==='ArrowUp')){event.preventDefault();buttons[(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length].focus();}
    };
    const escape=event=>{if(event.key==='Escape'&&!popup.hidden){event.preventDefault();event.stopImmediatePropagation();close(true);}};
    const outside=event=>{if(!popup.contains(event.target)&&!field.contains(event.target))close();};
    const scroll=event=>{if(!popup.contains(event.target))close();};
    overlay.addEventListener('keydown',escape,true);overlay.addEventListener('click',outside);
    window.addEventListener('resize',close);document.addEventListener('scroll',scroll,true);
    return ()=>{popup.remove();overlay.removeEventListener('keydown',escape,true);overlay.removeEventListener('click',outside);
      window.removeEventListener('resize',close);document.removeEventListener('scroll',scroll,true);};
  },
};
