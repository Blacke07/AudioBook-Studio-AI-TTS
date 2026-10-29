/* Visual, exact code-point boundaries. No source text is edited or sent to a model. */
const LineSplit = {
  points(line, all = false) {
    const chars = Array.from(line.text), points = new Map((line.split_points || []).map(p => [p.position, p.kind]));
    if (all) for (let i = 1; i < chars.length; i++) {
      if (/\s/u.test(chars[i - 1]) && !/\s/u.test(chars[i]) && chars.slice(0,i).join('').trim())
        if (!points.has(i)) points.set(i, 'Word boundary');
    }
    return [...points].sort((a,b) => a[0]-b[0]);
  },
  markup(line, all = false, selected = null) {
    const chars = Array.from(line.text); let start = 0;
    return this.points(line, all).map(([at,kind]) => {
      const text = chars.slice(start,at).join(''); start = at;
      return `${esc(text)}<button type="button" class="split-marker ${selected===at?'on':''}" data-cut="${at}" aria-pressed="${selected===at}" title="${esc(kind)}" aria-label="Split here: ${esc(kind)}; before ${esc(chars.slice(at,at+32).join(''))}">${icon('scissors')}</button>`;
    }).join('') + esc(chars.slice(start).join(''));
  },
  async editor(volume, stem, data, index, done) {
    const line = data.lines[index];
    let all = !(line.split_points || []).length, selected = null;
    const options = current => data.speakers.map(s => `<option value="${esc(s)}" ${s===current?'selected':''}>${esc(s)}</option>`).join('');
    const pending = modal('Split line', `<p class="small muted">Choose a scissors marker. Sentence ends and speech tags are suggested; show all word boundaries for another cut. The manuscript stays unchanged.</p>
      <label class="row"><input id="split-all" type="checkbox" ${all?'checked':''}> Show all word boundaries</label>
      <div class="split-text" id="split-text"></div><input type="hidden" name="position" id="split-position" value="">
      <div class="split-preview"><div><label class="field"><span>First segment — speaker</span><select name="first_speaker">${options(line.speaker)}</select></label><p id="split-first" class="small"></p></div>
      <div><label class="field"><span>Second segment — speaker</span><select name="speaker">${options(NARRATOR)}</select></label><p id="split-second" class="small"></p></div></div>`,
      [{label:'Cancel',value:null},{label:'Split',value:'form',primary:true}]);
    const root = document.querySelector('.overlay:last-child .modal'); root.classList.add('wide');
    const submit = root.querySelector('[data-i="1"]'); submit.disabled = true;
    const draw = () => {
      $('#split-text').innerHTML = this.markup(line, all, selected);
      $$('[data-cut]',root).forEach(button => button.onclick = () => {
        selected = Number(button.dataset.cut); $('#split-position').value = String(selected);
        const chars = Array.from(line.text);
        $('#split-first').textContent = chars.slice(0,selected).join('').trim();
        $('#split-second').textContent = chars.slice(selected).join('').trim();
        submit.disabled = false; draw();
      });
    };
    $('#split-all').onchange = e => { all=e.target.checked; draw(); };
    draw();
    const form = await pending;
    if (!form || form.position==='') return;
    await api('/api/chapter/split',{method:'POST',body:{volume,stem,index,source_hash:data.source_hash,
      script_revision:data.script_revision,position:Number(form.position),first_speaker:form.first_speaker,speaker:form.speaker}});
    await done(index);
  },
};
