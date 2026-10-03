/** Keep the mobile navigation and the visible workspace in separate focus scopes. */
export function createNavigation({ sidebar, toggle, backdrop, main, workspace }) {
  if (![sidebar, toggle, backdrop, main, workspace].every(Boolean)) throw new Error('导航缺少必要元素');
  const document = sidebar.ownerDocument, window = document.defaultView;
  const media = window.matchMedia('(max-width: 800px)');
  let open = false, opener = toggle, focusedElement = document.activeElement;

  const visible = element => element?.isConnected && !element.closest('[inert]') && element.getClientRects().length > 0 && window.getComputedStyle(element).visibility !== 'hidden';
  const controls = () => [...sidebar.querySelectorAll('a[href], button, input, select, textarea, summary, [tabindex], [contenteditable="true"]')]
    .filter(element => element.tabIndex >= 0 && !element.disabled && visible(element));
  function focusNavigation() {
    const items = controls();
    (items.find(element => element.getAttribute('aria-current') === 'page') || items[0] || sidebar).focus();
  }
  function setOpen(requested, { restoreFocus = true } = {}) {
    const previous = open;
    open = Boolean(requested && media.matches);
    if (open && !previous) opener = sidebar.contains(document.activeElement) ? toggle : document.activeElement;
    if (open || !media.matches) sidebar.removeAttribute('aria-hidden');
    main.inert = open;
    sidebar.inert = media.matches && !open;
    document.body.classList.toggle('nav-open', open);
    backdrop.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? '关闭导航' : '打开导航');
    if (open) {
      sidebar.setAttribute('role', 'dialog');
      sidebar.setAttribute('aria-modal', 'true');
      if (!previous) focusNavigation();
    } else {
      sidebar.removeAttribute('role');
      sidebar.removeAttribute('aria-modal');
      if (previous && restoreFocus) (visible(opener) ? opener : media.matches ? toggle : workspace).focus({ preventScroll: true });
      if (media.matches) sidebar.setAttribute('aria-hidden', 'true');
    }
  }
  function focusWorkspace() {
    setOpen(false, { restoreFocus: false });
    workspace.focus();
  }
  function onToggle() { setOpen(!open); }
  function onClose() { setOpen(false); }
  function onSidebarClick(event) {
    if (event.target.closest('[data-close-navigation]')) { onClose(); return; }
    const link = event.target.closest('a[href^="#"]');
    if (link && !event.defaultPrevented && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey && event.button === 0) focusWorkspace();
  }
  function onKeydown(event) {
    if (!open) return;
    if (event.key === 'Escape') { event.preventDefault(); onClose(); return; }
    if (event.key !== 'Tab') return;
    const items = controls(), first = items[0], last = items.at(-1);
    if (!items.length) { event.preventDefault(); sidebar.focus(); }
    else if (!items.includes(document.activeElement)) { event.preventDefault(); (event.shiftKey ? last : first).focus(); }
    else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
  function onFocus(event) {
    focusedElement = event.target;
    if (open && !sidebar.contains(event.target)) focusNavigation();
  }
  function onFocusOut(event) {
    // Layout may hide a focused control before matchMedia dispatches its change.
    // Preserve that owner; a deliberate blur of a visible control clears it.
    if (!event.relatedTarget && event.target === focusedElement && visible(event.target)) focusedElement = null;
  }
  function onResize() {
    const active = document.activeElement;
    const previousFocus = active === document.body || active === document.documentElement ? focusedElement : active;
    setOpen(false, { restoreFocus: false });
    if (media.matches && sidebar.contains(previousFocus)) toggle.focus({ preventScroll: true });
    else if (!media.matches && previousFocus && !visible(previousFocus)) workspace.focus({ preventScroll: true });
  }
  const listeners = [[toggle, 'click', onToggle], [backdrop, 'click', onClose], [sidebar, 'click', onSidebarClick],
    [document, 'keydown', onKeydown], [document, 'focusin', onFocus], [document, 'focusout', onFocusOut],
    [window, 'hashchange', focusWorkspace], [media, 'change', onResize]];
  listeners.forEach(([target, event, listener]) => target.addEventListener(event, listener));
  setOpen(false);
  return {
    setOpen,
    destroy() {
      listeners.forEach(([target, event, listener]) => target.removeEventListener(event, listener));
      setOpen(false, { restoreFocus: false });
      sidebar.inert = false;
      sidebar.removeAttribute('aria-hidden');
    },
  };
}
