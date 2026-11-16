/* Detection-only dashboard: a thin browser client of the existing FastAPI API.
   No SQLite access, client-side matching, or automatic order completion. */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const palette = ['#3b82f6', '#16a34a', '#e17b16', '#9065cf', '#0891b2', '#c45c9a', '#c89926', '#54758c', '#c05b55', '#4f907c'];
  const state = {
    drivers: [],
    search: '',
    progressFilter: 'all',
    selectedDriver: null,
    expansion: new Map(),
    pending: new Set(),
    lastData: '',
    requestSerial: 0,
  };
  const groups = $('order-groups');

  function escapeHTML(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[char]));
  }

  function color(index) { return palette[index % palette.length]; }
  function driverId(index) { return `D${String(index + 1).padStart(2, '0')}`; }
  function percent(completed, required) { return required ? Math.round(100 * completed / required) : 0; }
  function groupKey(...parts) { return parts.map((part) => String(part ?? '_')).join('::'); }
  function openAttr(key, fallback = true) {
    return (state.expansion.has(key) ? state.expansion.get(key) : fallback) ? ' open' : '';
  }
  function rememberExpansion() {
    document.querySelectorAll('details[data-group-key]').forEach((el) => {
      state.expansion.set(el.dataset.groupKey, el.open);
    });
  }

  function setConnection(online) {
    $('health').classList.toggle('online', online);
    $('health').classList.toggle('offline', !online);
    $('health-text').textContent = online ? 'Backend connected' : 'Backend unavailable';
  }

  function message(text, isError = false) {
    const el = $('system-message');
    el.textContent = text;
    el.className = `system-message ${text ? 'visible' : ''} ${isError ? 'error' : ''}`;
  }

  function allLines() {
    return state.drivers.flatMap((d) => d.clients.flatMap((c) => c.orders.flatMap((o) => o.requirements)));
  }

  function renderStats() {
    const rows = allLines();
    const clients = state.drivers.reduce((count, d) => count + d.clients.length, 0);
    const completed = rows.reduce((sum, r) => sum + r.completed_quantity, 0);
    const required = rows.reduce((sum, r) => sum + r.required_quantity, 0);
    $('stat-drivers').textContent = String(state.drivers.length);
    $('stat-clients').textContent = String(clients);
    $('stat-requirements').textContent = String(rows.length);
    $('stat-completed').textContent = String(completed);
    $('stat-required').textContent = String(required);
    $('overall-bar').style.width = `${percent(completed, required)}%`;
    $('sidebar-driver-count').textContent = String(state.drivers.length);
  }

  function renderNav() {
    $('driver-nav').innerHTML = state.drivers.map((d, i) => {
      const active = state.selectedDriver === d.driver;
      return `<button type="button" class="nav-driver${active ? ' active' : ''}" data-driver-index="${i}" style="--accent:${color(i)}" aria-pressed="${active}">
        <span class="driver-badge">${driverId(i)}</span>
        <span class="nav-name">${escapeHTML(d.driver)}</span>
        <span class="nav-remain">${d.remaining_quantity} left</span>
      </button>`;
    }).join('') || '<p class="muted">No drivers found.</p>';
  }

  function lineMatchesFilter(r) {
    if (state.progressFilter === 'outstanding' && r.remaining_quantity === 0) return false;
    if (state.progressFilter === 'completed' && r.remaining_quantity > 0) return false;
    return true;
  }

  function viewDrivers() {
    const term = state.search.trim().toLowerCase();
    return state.drivers.map((driver, i) => {
      if (state.selectedDriver && state.selectedDriver !== driver.driver) return null;
      const driverMatch = driver.driver.toLowerCase().includes(term) || driverId(i).toLowerCase().includes(term);
      const clients = driver.clients.map((client) => {
        const clientMatch = driverMatch || client.client.toLowerCase().includes(term);
        const orders = client.orders.map((order) => {
          const orderName = order.order_id ?? 'Single order';
          const orderMatch = clientMatch || orderName.toLowerCase().includes(term);
          const requirements = order.requirements.filter((r) =>
            lineMatchesFilter(r) && (orderMatch || r.product.toLowerCase().includes(term))
          );
          return requirements.length ? { ...order, requirements } : null;
        }).filter(Boolean);
        return orders.length ? { ...client, orders } : null;
      }).filter(Boolean);
      return clients.length ? { ...driver, paletteIndex: i, clients } : null;
    }).filter(Boolean);
  }

  function renderRow(r) {
    const completed = r.completed_quantity;
    const required = r.required_quantity;
    const done = r.remaining_quantity === 0;
    const title = `${r.product}, ${completed} of ${required} completed`;
    return `<div class="product-row" data-requirement-id="${r.id}">
      <div><div class="product-name">${escapeHTML(r.product)}</div><span class="product-note${done ? ' done' : ''}">${done ? 'Completed · no remaining demand' : `${r.remaining_quantity} remaining`}</span></div>
      <div class="product-bar-wrap"><div class="bar"><div class="bar-fill" style="width:${percent(completed, required)}%"></div></div><span class="product-fraction">${completed}/${required}</span></div>
      <div class="quantity" aria-label="Edit ${escapeHTML(title)}">
        <button type="button" class="quantity-btn" data-action="minus" aria-label="Decrease completed quantity of ${escapeHTML(r.product)}" ${completed === 0 ? 'disabled' : ''}>−</button>
        <input class="quantity-input" type="number" inputmode="numeric" min="0" max="${required}" step="1" value="${completed}" aria-label="Completed quantity for ${escapeHTML(r.product)}" data-original="${completed}">
        <span class="quantity-total">/ ${required}</span>
        <button type="button" class="quantity-btn" data-action="plus" aria-label="Increase completed quantity of ${escapeHTML(r.product)}" ${completed === required ? 'disabled' : ''}>+</button>
      </div>
    </div>`;
  }

  function renderOrder(driver, client, order, index) {
    const key = groupKey('order', driver.driver, client.client, order.order_id);
    const title = order.order_id ?? 'Single order';
    return `<details class="order-group" data-group-key="${escapeHTML(key)}" ${openAttr(key)}>
      <summary><strong>${escapeHTML(title)}</strong><span class="order-meta">${order.requirements.length} product line${order.requirements.length === 1 ? '' : 's'}</span></summary>
      <div class="product-table">${order.requirements.map(renderRow).join('')}</div>
    </details>`;
  }

  function renderClient(driver, client) {
    const key = groupKey('client', driver.driver, client.client);
    const lineCount = client.orders.reduce((sum, o) => sum + o.requirements.length, 0);
    return `<details class="client-group" data-group-key="${escapeHTML(key)}" ${openAttr(key)}>
      <summary><strong>${escapeHTML(client.client)}</strong><span class="meta">${client.orders.length} order${client.orders.length === 1 ? '' : 's'} · ${lineCount} lines</span></summary>
      <div class="client-body">${client.orders.map((order, i) => renderOrder(driver, client, order, i)).join('')}</div>
    </details>`;
  }

  function renderDriver(driver) {
    const key = groupKey('driver', driver.driver);
    const i = driver.paletteIndex;
    return `<details class="driver-group" data-group-key="${escapeHTML(key)}" style="--accent:${color(i)}" ${openAttr(key, state.drivers.length <= 5 || i === 0)}>
      <summary><span class="driver-mark">${driverId(i)}</span><span class="driver-title"><strong>${escapeHTML(driver.driver)}</strong><small>${driver.clients.length} client${driver.clients.length === 1 ? '' : 's'}</small></span>
        <span class="group-progress"><span class="bar"><span class="bar-fill" style="width:${percent(driver.completed_quantity, driver.required_quantity)}%"></span></span><span class="group-count">${driver.completed_quantity}/${driver.required_quantity} units</span></span>
      </summary><div class="driver-body">${driver.clients.map((client) => renderClient(driver, client)).join('')}</div>
    </details>`;
  }

  function render() {
    rememberExpansion();
    renderStats();
    renderNav();
    const filtered = viewDrivers();
    groups.innerHTML = filtered.length ? filtered.map(renderDriver).join('') : '<div class="empty">No requirements match your search and filters.</div>';
  }

  async function reload(force = false) {
    const focusedInput = document.activeElement?.classList?.contains('quantity-input');
    if (!force && (state.pending.size || focusedInput)) return;
    const serial = ++state.requestSerial;
    try {
      const response = await fetch('/api/orders', { cache: 'no-store' });
      if (!response.ok) throw new Error(`Orders request failed (${response.status})`);
      const tree = await response.json();
      if (!Array.isArray(tree.drivers)) throw new Error('Unexpected server response');
      if (serial !== state.requestSerial || (!force && (state.pending.size || document.activeElement?.classList?.contains('quantity-input')))) return;
      setConnection(true);
      const signature = JSON.stringify(tree.drivers);
      if (signature !== state.lastData) {
        state.drivers = tree.drivers;
        state.lastData = signature;
        render();
      }
      $('last-update').textContent = `Last checked ${new Date().toLocaleTimeString()}`;
      if (!state.pending.size) message('');
    } catch (error) {
      if (serial !== state.requestSerial) return;
      setConnection(false);
      message(`${error.message}. Verify the FastAPI server is running.`, true);
    }
  }

  function findRequirement(id) {
    return allLines().find((r) => r.id === id);
  }

  async function setCompleted(id, quantity) {
    const existing = findRequirement(id);
    if (!existing || state.pending.has(id)) return;
    if (!Number.isInteger(quantity) || quantity < 0 || quantity > existing.required_quantity) {
      message(`Enter a whole number from 0 to ${existing.required_quantity}.`, true);
      const row = groups.querySelector(`[data-requirement-id="${id}"]`);
      if (row) row.querySelector('.quantity-input').value = String(existing.completed_quantity);
      return;
    }
    if (quantity === existing.completed_quantity) return;
    ++state.requestSerial; // Prevent an older polling response replacing the newer state.
    state.pending.add(id);
    const row = groups.querySelector(`[data-requirement-id="${id}"]`);
    if (row) {
      row.querySelector('.quantity').classList.add('saving');
      row.querySelectorAll('button, input').forEach((el) => { el.disabled = true; });
    }
    let saveError = null;
    try {
      const response = await fetch(`/api/requirements/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ completed_quantity: quantity }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const detail = typeof data.detail === 'string' ? data.detail : `Server rejected the update (${response.status})`;
        throw new Error(detail);
      }
      const updated = await response.json();
      if (updated.completed_quantity !== quantity) throw new Error('Server returned an unexpected quantity');
      setConnection(true);
      message('');
    } catch (error) {
      saveError = `Could not save quantity: ${error.message}`;
    } finally {
      state.pending.delete(id);
      await reload(true);
      if (saveError) message(saveError, true);
    }
  }

  $('search').addEventListener('input', (event) => {
    state.search = event.target.value;
    render();
  });
  document.querySelectorAll('button[data-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      state.progressFilter = button.dataset.filter;
      document.querySelectorAll('button[data-filter]').forEach((b) => {
        const active = b === button;
        b.classList.toggle('active', active);
        b.setAttribute('aria-pressed', String(active));
      });
      render();
    });
  });
  $('driver-nav').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-driver-index]');
    if (!button) return;
    const driver = state.drivers[Number(button.dataset.driverIndex)]?.driver;
    state.selectedDriver = state.selectedDriver === driver ? null : driver;
    render();
  });

  groups.addEventListener('input', (event) => {
    const input = event.target.closest('.quantity-input');
    if (!input) return;
    const row = input.closest('[data-requirement-id]');
    const required = findRequirement(Number(row.dataset.requirementId))?.required_quantity;
    const valid = /^\d+$/.test(input.value) && Number.isSafeInteger(Number(input.value)) && Number(input.value) <= required;
    input.classList.toggle('invalid', !valid);
    input.setAttribute('aria-invalid', String(!valid));
  });

  groups.addEventListener('keydown', (event) => {
    const input = event.target.closest('.quantity-input');
    if (!input) return;
    if (event.key === 'Enter') { event.preventDefault(); input.blur(); }
    if (event.key === 'Escape') {
      const r = findRequirement(Number(input.closest('[data-requirement-id]').dataset.requirementId));
      if (r) input.value = String(r.completed_quantity);
      input.blur();
    }
  });

  groups.addEventListener('focusout', (event) => {
    const input = event.target.closest('.quantity-input');
    if (!input || input.disabled) return;
    const id = Number(input.closest('[data-requirement-id]').dataset.requirementId);
    const current = findRequirement(id);
    if (!current) return;
    const text = input.value.trim();
    if (!/^\d+$/.test(text) || !Number.isSafeInteger(Number(text)) || Number(text) > current.required_quantity) {
      message(`Invalid quantity for ${current.product}. Enter 0–${current.required_quantity}.`, true);
      input.value = String(current.completed_quantity);
      input.classList.remove('invalid');
      return;
    }
    input.classList.remove('invalid');
    void setCompleted(id, Number(text));
  });

  // Keeping focus prevents an unsaved number input's blur handler from racing
  // the nearby + / − action. The buttons use the server-confirmed quantity.
  groups.addEventListener('pointerdown', (event) => {
    if (event.target.closest('button[data-action]')) event.preventDefault();
  });
  groups.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button || button.disabled) return;
    const id = Number(button.closest('[data-requirement-id]').dataset.requirementId);
    const current = findRequirement(id);
    if (!current) return;
    const delta = button.dataset.action === 'plus' ? 1 : -1;
    void setCompleted(id, current.completed_quantity + delta);
  });

  void reload(true);
  window.setInterval(() => void reload(false), 3000);
})();
