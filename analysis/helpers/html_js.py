# -*- coding: utf-8 -*-
JS = r"""
(function () {
  function setupFilterGroup(root) {
    var chips = root.querySelectorAll('.chip');
    var search = root.querySelector('input[type="search"]');
    var items = root._items;
    if (!items || !items.length) return;

    function apply() {
      var active = root.querySelector('.chip.active');
      var filter = active ? active.getAttribute('data-filter') : 'all';
      var q = search ? search.value.trim().toLowerCase() : '';
      var visible = 0;
      items.forEach(function (el) {
        var tenets = (el.getAttribute('data-tenets') || el.getAttribute('data-tenet') || '');
        var matchesFilter = filter === 'all' || tenets.indexOf(filter) !== -1;
        var haystack = (el.getAttribute('data-search') || el.getAttribute('data-name') || el.textContent || '').toLowerCase();
        var matchesSearch = q === '' || haystack.indexOf(q) !== -1;
        var show = matchesFilter && matchesSearch;
        if (el.tagName === 'TR') {
          el.style.display = show ? '' : 'none';
        } else {
          el.style.display = show ? '' : 'none';
        }
        if (show) visible++;
      });
      var counter = root.querySelector('.count-hint');
      if (counter) counter.textContent = 'Showing ' + visible + ' of ' + items.length + '.';
    }

    chips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        chips.forEach(function (c) { c.classList.remove('active'); });
        chip.classList.add('active');
        apply();
      });
    });
    if (search) search.addEventListener('input', apply);
    apply();
  }

  var repoRoot = document.getElementById('repo-filter-root');
  if (repoRoot) {
    repoRoot._items = Array.prototype.slice.call(document.querySelectorAll('.repo-card'));
    setupFilterGroup(repoRoot);
  }
  var checklistRoot = document.getElementById('checklist-filter-root');
  if (checklistRoot) {
    checklistRoot._items = Array.prototype.slice.call(document.querySelectorAll('#checklist-body tr'));
    setupFilterGroup(checklistRoot);
  }

  // Smooth-scroll offset for sticky nav is handled by CSS scroll-behavior + scroll-margin-top.
})();
"""
