/* Editable audition drafts stay on this page; switching presets never changes saved voices/settings. */
const NarratorPassages = {
  create(prose) {
    const drafts={prose,dialogue:'“You came back,” she said quietly.\n\n“I said I would.” He set the lantern on the table. “Did you really think I would leave you here?”\n\nShe looked at the door, then back at him. “No,” she replied. “But I was beginning to wonder what had taken you so long.”'};
    let selected='prose';
    return {
      text:()=>drafts[selected],
      save(text){drafts[selected]=text;},
      choose(key,text){
        if(!Object.hasOwn(drafts,key))throw new Error('Choose Prose or Dialogue.');
        drafts[selected]=text;selected=key;return drafts[selected];
      },
      html(){
        return `<div class="seg preview-presets" role="group" aria-label="Preview text preset">${['prose','dialogue'].map(key=>`<button type="button" data-preview-preset="${key}" class="${selected===key?'on':''}" aria-pressed="${selected===key}">${key==='prose'?'Prose':'Dialogue'}</button>`).join('')}</div>
          <label class="field"><span>Preview text</span><textarea id="sample" rows="7">${esc(drafts[selected])}</textarea><small>Both presets are editable. Dialogue includes speech tags such as “he said” and “she replied” to audition the narrator reading a conversation.</small></label>`;
      },
      bind(root){
        const input=root.querySelector('#sample'), buttons=[...root.querySelectorAll('[data-preview-preset]')];
        input.oninput=()=>this.save(input.value);
        buttons.forEach(button=>button.onclick=()=>{
          input.value=this.choose(button.dataset.previewPreset,input.value);
          buttons.forEach(item=>{const on=item.dataset.previewPreset===selected;item.classList.toggle('on',on);item.setAttribute('aria-pressed',String(on));});
        });
      },
    };
  },
};
