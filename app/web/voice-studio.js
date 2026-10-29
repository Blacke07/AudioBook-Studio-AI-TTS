/* The registry owns identity/order; this module owns only studio selection and view state. */
const VoiceStudio = {
  selected: '', volume: 'all', closed: new Set(), browserSections: new Map(), editors: new Map(), browserScroll: 0,
  groups(data, query = characterQuery) {
    const registry = data.registry, org = registry.document.organization;
    const byName = new Map(data.characters.map((c, i) => [c.name, {c, i}]));
    return org.categories.map((category, index) => ({category, priority: index + 1,
      people: registry.document.characters.flatMap((record) => {
        const person = byName.get(record.name), meta = org.characters[record.name];
        if (!person || meta.category !== category.id) return [];
        if (this.volume !== 'all' && meta.volumes?.length && !meta.volumes.includes(this.volume)) return [];
        if (query && ![record.name, meta.label, person.c.aliases, person.c.note].join(' ').toLowerCase().includes(query)) return [];
        return [{...person, meta}];
      })}));
  },
  selection(data) {
    if (this.volume !== 'all' && !data.registry.volumes.some(v => v.id === this.volume)) this.volume = 'all';
    const people = this.groups(data).flatMap(group => group.people);
    const person = people.find(({c}) => c.name === this.selected) || people[0];
    this.selected = person?.c.name || '';
    return person;
  },
  tile({c, meta}, emotions) {
    const count = Object.keys(c.fixed?.takes || {}).length;
    return `<button type="button" class="studio-character ${c.name === this.selected ? 'selected' : ''}" data-studio-character="${esc(c.name)}" aria-pressed="${c.name === this.selected}" aria-controls="studio-editor" title="${esc(c.name)}">
      <span class="studio-tile-name"><i class="dot" style="background:${colorFor(c.name)}"></i><b>${esc(c.name)}</b></span>
      <span class="studio-reading" title="Read as: ${esc(c.read_as || c.name)}">Read as: ${esc(c.read_as || c.name)}</span>
      <span class="studio-tile-status"><span class="${c.fixed ? 'fixed-status' : 'review-status'}">${icon(c.fixed ? 'lock' : 'info')} ${c.fixed ? 'Fixed voice' : 'Voice to review'}</span><span class="small muted" data-studio-emotions>Emotions ${count}/${emotions}</span></span>
      ${meta.status !== 'approved' ? `<span class="studio-review small">${meta.status === 'provisional' ? 'Provisional identity' : 'Identity needs review'}</span>` : ''}</button>`;
  },
  catalogue(data) {
    const groups = this.groups(data), total = (data.emotions || []).filter(e => e.key !== 'neutral').length;
    if (!groups.some(g => g.people.length)) return '<p class="empty">No characters match these filters.</p>';
    return groups.filter(g => g.people.length).map(({category, priority, people}) =>
      `<details class="studio-category" data-studio-category="${esc(category.id)}" ${!this.closed.has(category.id) || characterQuery ? 'open' : ''}>
        <summary><span>${esc(category.name)}</span><span class="small muted">Priority ${priority} · ${people.length}</span></summary>
        <div class="studio-tiles">${people.map(person => this.tile(person, total)).join('')}</div></details>`).join('');
  },
  capture(root) {
    const browser = root.querySelector('.voice-studio-browser');
    if (browser) {
      this.browserScroll = browser.scrollTop;
      browser.querySelectorAll('[data-studio-category]').forEach(el => {
        if (el.open) this.closed.delete(el.dataset.studioCategory); else this.closed.add(el.dataset.studioCategory);
      });
      browser.querySelectorAll('[data-studio-browser-section]').forEach(el => this.browserSections.set(el.dataset.studioBrowserSection, el.open));
    }
    const editor = root.querySelector('#studio-editor');
    if (!editor?.dataset.character) return;
    const sections = {};
    editor.querySelectorAll('[data-studio-section]').forEach(el => { sections[el.dataset.studioSection] = el.open; });
    const emotions = {};
    editor.querySelectorAll('[data-emotion-take]').forEach(el => {
      emotions[el.dataset.emotionTake] = {open: el.open,
        text: el.querySelector('[data-emotion-text]').value, seed: el.querySelector('[data-emotion-seed]').value};
    });
    this.editors.set(editor.dataset.character, {scroll: editor.scrollTop, sections, emotions});
  },
  restore(root) {
    const browser = root.querySelector('.voice-studio-browser');
    browser.querySelectorAll('[data-studio-browser-section]').forEach(el => {
      if (this.browserSections.has(el.dataset.studioBrowserSection)) el.open = this.browserSections.get(el.dataset.studioBrowserSection);
    });
    const editor = root.querySelector('#studio-editor'), saved = this.editors.get(editor.dataset.character);
    if (saved) {
      editor.querySelectorAll('[data-studio-section]').forEach(el => {
        if (Object.hasOwn(saved.sections, el.dataset.studioSection)) el.open = saved.sections[el.dataset.studioSection];
      });
      editor.querySelectorAll('[data-emotion-take]').forEach(el => {
        const state = saved.emotions[el.dataset.emotionTake];
        if (!state) return;
        el.open = state.open;
        el.querySelector('[data-emotion-text]').value = state.text;
        el.querySelector('[data-emotion-seed]').value = state.seed;
      });
      editor.scrollTop = saved.scroll;
    }
    browser.scrollTop = this.browserScroll;
  },
  bind(root, data, draw) {
    root.querySelectorAll('[data-studio-character]').forEach(button => button.onclick = () => {
      if (button.dataset.studioCharacter === this.selected) return;
      this.capture(root);
      root.querySelectorAll('#studio-editor audio').forEach(audio => audio.pause());
      this.selected = button.dataset.studioCharacter;
      draw();
    });
    this.restore(root);
  },
  referenceChanged(data, role, fixed, root = view) {
    const character = data.characters.find(c => c.name === role);
    if (character) character.fixed = fixed;
    // Update the summary without replacing the editor, its controls, focus or scroll position.
    const tile = [...root.querySelectorAll('[data-studio-character]')].find(el => el.dataset.studioCharacter === role);
    if (tile) tile.querySelector('[data-studio-emotions]').textContent =
      `Emotions ${Object.keys(fixed?.takes || {}).length}/${data.emotions.filter(e => e.key !== 'neutral').length}`;
  },
};
