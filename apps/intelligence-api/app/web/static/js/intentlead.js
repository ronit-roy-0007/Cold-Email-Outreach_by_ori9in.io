/**
 * IntentLead AI — Client Interactivity & UI Utilities
 */

document.addEventListener('DOMContentLoaded', () => {
  // Mobile Sidebar Drawer Toggle
  const mobileToggle = document.getElementById('mobile-toggle');
  const sidebar = document.getElementById('sidebar');
  const sidebarOverlay = document.getElementById('sidebar-overlay');

  if (mobileToggle && sidebar) {
    mobileToggle.addEventListener('click', () => {
      sidebar.classList.toggle('open');
      if (sidebarOverlay) sidebarOverlay.classList.toggle('open');
    });
  }

  if (sidebarOverlay && sidebar) {
    sidebarOverlay.addEventListener('click', () => {
      sidebar.classList.remove('open');
      sidebarOverlay.classList.remove('open');
    });
  }

  // Quick Table Search Filter
  const tableSearch = document.getElementById('table-search');
  if (tableSearch) {
    tableSearch.addEventListener('input', (e) => {
      const term = e.target.value.toLowerCase().trim();
      const rows = document.querySelectorAll('table.data-table tbody tr');
      rows.forEach(row => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(term) ? '' : 'none';
      });
    });
  }

  // Filter Chips Functionality
  const filterChips = document.querySelectorAll('.filter-chip[data-filter-group]');
  filterChips.forEach(chip => {
    chip.addEventListener('click', () => {
      const group = chip.getAttribute('data-filter-group');
      const val = chip.getAttribute('data-filter-val');
      
      document.querySelectorAll(`.filter-chip[data-filter-group="${group}"]`).forEach(c => c.classList.remove('active'));
      chip.classList.add('active');

      const rows = document.querySelectorAll('table.data-table tbody tr');
      rows.forEach(row => {
        if (!val || val === 'all') {
          row.style.display = '';
        } else {
          const rowVal = row.getAttribute(`data-${group}`);
          row.style.display = (rowVal === val) ? '' : 'none';
        }
      });
    });
  });
});

// Toast System
function showToast(message, type = 'info') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span style="color: var(--accent-lime); font-size: 1.1rem;">⚡</span>
    <span>${message}</span>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Modal Controllers
function openModal(id) {
  const modal = document.getElementById(id);
  if (modal) {
    modal.classList.add('open');
    document.body.style.overflow = 'hidden';
  }
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (modal) {
    modal.classList.remove('open');
    document.body.style.overflow = '';
  }
}

// API Action: Process Lead Approval / Rejection
async function handleLeadApproval(leadId, action) {
  const btn = event?.currentTarget;
  if (btn) btn.disabled = true;

  try {
    const res = await fetch(`/api/web/approvals/${leadId}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        user_id: 'api_operator',
        action: action
      })
    });

    const data = await res.json();
    if (res.ok) {
      showToast(`Lead ${action === 'approve' ? 'Approved' : 'Rejected'} Successfully!`, 'success');
      // Update UI row or card if present
      const row = document.getElementById(`lead-row-${leadId}`);
      if (row) {
        const badge = row.querySelector('.status-cell .badge');
        if (badge) {
          badge.className = `badge badge-${action === 'approve' ? 'approved' : 'failed'}`;
          badge.textContent = action === 'approve' ? 'Approved' : 'Rejected';
        }
        const actionCell = row.querySelector('.actions-cell');
        if (actionCell) {
          actionCell.innerHTML = `<span class="micro-label" style="color: var(--accent-mint);">[ ${action.toUpperCase()}D ]</span>`;
        }
      }
      // If inside approval modal or drawer, close or advance
      const modal = document.getElementById(`modal-approval-${leadId}`);
      if (modal) closeModal(`modal-approval-${leadId}`);
    } else {
      showToast(`Error: ${data.detail || data.message || 'Operation failed'}`, 'error');
    }
  } catch (err) {
    showToast(`Network Error: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Copy to Clipboard
function copyText(text, label = 'Copied') {
  navigator.clipboard.writeText(text).then(() => {
    showToast(`${label} to clipboard!`);
  }).catch(() => {
    showToast('Failed to copy', 'error');
  });
}
