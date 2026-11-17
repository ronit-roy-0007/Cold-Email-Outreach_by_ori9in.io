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

// ==========================================
// AI Draft Studio Controllers
// ==========================================

function setDraftAlert(message, type = 'info') {
  const alertBox = document.getElementById('draft-alert');
  if (!alertBox) return;
  if (!message) {
    alertBox.style.display = 'none';
    alertBox.textContent = '';
    return;
  }

  let bg = '#F0F9FF', border = '#0284C7', color = '#0369A1';
  if (type === 'success') {
    bg = '#F0FDF4'; border = '#16A34A'; color = '#15803D';
  } else if (type === 'error') {
    bg = '#FEF2F2'; border = '#DC2626'; color = '#B91C1C';
  } else if (type === 'warning') {
    bg = '#FFFBEB'; border = '#D97706'; color = '#B45309';
  }

  alertBox.style.display = 'block';
  alertBox.style.backgroundColor = bg;
  alertBox.style.border = `1.5px solid ${border}`;
  alertBox.style.color = color;
  alertBox.innerHTML = message;
}

function setDraftStatusBadge(text, className) {
  const badge = document.getElementById('draft-status-badge');
  if (badge) {
    badge.className = `badge ${className}`;
    badge.textContent = text;
  }
}

function handleDraftInput() {
  const hasUnsaved = document.getElementById('draft-has-unsaved');
  if (hasUnsaved) hasUnsaved.value = 'true';
  setDraftStatusBadge('Unsaved Edits', 'badge-neutral');
  setDraftAlert('You have unsaved edits. Click <strong>Save Draft</strong> to persist them.', 'warning');
}

async function generateAiDraft(leadId, isRegenerate = false) {
  const hasUnsaved = document.getElementById('draft-has-unsaved')?.value === 'true';
  if (isRegenerate && hasUnsaved) {
    const proceed = confirm("You have unsaved changes in your draft. Do you want to overwrite them with a newly generated AI draft?");
    if (!proceed) return;
  }

  const btnGen = document.getElementById('btn-ai-generate');
  const btnRegen = document.getElementById('btn-ai-regenerate');
  const btnSave = document.getElementById('btn-save-draft');
  const spinGen = document.getElementById('btn-generate-spinner');
  const spinRegen = document.getElementById('btn-regen-spinner');

  if (btnGen) btnGen.disabled = true;
  if (btnRegen) btnRegen.disabled = true;
  if (btnSave) btnSave.disabled = true;
  if (isRegenerate && spinRegen) spinRegen.style.display = 'inline';
  if (!isRegenerate && spinGen) spinGen.style.display = 'inline';

  setDraftAlert('⏳ Analyzing website audit evidence & generating personalized draft with Google Gemini...', 'info');

  try {
    const res = await fetch(`/api/leads/${leadId}/ai-generate`, {
      method: 'POST',
      headers: {
        'Accept': 'application/json',
      },
    });

    const data = await res.json();
    if (!res.ok) {
      const errorMsg = data.detail || data.message || 'Draft generation failed';
      setDraftAlert(`❌ Generation Error: ${errorMsg}`, 'error');
      showToast(`Error: ${errorMsg}`, 'error');
      return;
    }

    // Populate Fields
    const subjectInput = document.getElementById('draft-subject-input');
    const bodyTextarea = document.getElementById('draft-body-textarea');
    const editorFields = document.getElementById('draft-editor-fields');

    if (subjectInput) subjectInput.value = data.draft.subject || '';
    if (bodyTextarea) bodyTextarea.value = data.draft.body || '';
    if (editorFields) editorFields.style.display = 'block';

    // Show action buttons
    if (btnRegen) btnRegen.style.display = 'inline-block';
    if (btnSave) btnSave.style.display = 'inline-block';
    ['btn-copy-subject', 'btn-copy-body', 'btn-copy-full'].forEach(id => {
      const btn = document.getElementById(id);
      if (btn) btn.style.display = 'inline-block';
    });

    const hasUnsavedTracker = document.getElementById('draft-has-unsaved');
    if (hasUnsavedTracker) hasUnsavedTracker.value = 'true';
    setDraftStatusBadge('Preview — Unsaved', 'badge-draft');
    setDraftAlert('✨ Generated draft preview ready! Review or customize above, then click <strong>Save Draft</strong>.', 'success');
    showToast('AI draft generated successfully!', 'success');
  } catch (err) {
    setDraftAlert(`❌ Network Error: Could not connect to API server (${err.message}).`, 'error');
    showToast(`Network Error: ${err.message}`, 'error');
  } finally {
    if (btnGen) btnGen.disabled = false;
    if (btnRegen) btnRegen.disabled = false;
    if (btnSave) btnSave.disabled = false;
    if (spinGen) spinGen.style.display = 'none';
    if (spinRegen) spinRegen.style.display = 'none';
  }
}

async function saveAiDraft(leadId) {
  const subjectInput = document.getElementById('draft-subject-input');
  const bodyTextarea = document.getElementById('draft-body-textarea');
  const versionInput = document.getElementById('draft-version');
  const btnSave = document.getElementById('btn-save-draft');
  const spinSave = document.getElementById('btn-save-spinner');

  const subject = (subjectInput?.value || '').trim();
  const body = (bodyTextarea?.value || '').trim();
  const version = parseInt(versionInput?.value || '1', 10);

  if (!subject) {
    showToast('Subject line cannot be blank.', 'error');
    subjectInput?.focus();
    return;
  }
  if (!body) {
    showToast('Email body cannot be blank.', 'error');
    bodyTextarea?.focus();
    return;
  }

  if (btnSave) btnSave.disabled = true;
  if (spinSave) spinSave.style.display = 'inline';
  setDraftAlert('💾 Saving personalized draft to PostgreSQL...', 'info');

  try {
    const res = await fetch(`/api/leads/${leadId}/ai-draft`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({
        subject: subject,
        body: body,
        version: version,
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      if (res.status === 409) {
        setDraftAlert(`⚠️ Version Conflict: ${data.detail || 'This draft was updated elsewhere. Please refresh the page.'}`, 'error');
        showToast('Version conflict! Please refresh.', 'error');
      } else {
        const errorMsg = data.detail || data.message || 'Save failed';
        setDraftAlert(`❌ Save Error: ${errorMsg}`, 'error');
        showToast(`Save Error: ${errorMsg}`, 'error');
      }
      return;
    }

    if (versionInput) versionInput.value = data.draft.version;
    const hasUnsavedTracker = document.getElementById('draft-has-unsaved');
    if (hasUnsavedTracker) hasUnsavedTracker.value = 'false';

    setDraftStatusBadge(`Saved (v${data.draft.version})`, 'badge-approved');
    const metaText = document.getElementById('draft-meta-text');
    if (metaText) {
      metaText.textContent = `Last saved: Just now (v${data.draft.version})`;
    }

    setDraftAlert('✓ Draft successfully saved and linked to lead! Changes will persist across reloads.', 'success');
    showToast(`Draft v${data.draft.version} saved!`, 'success');
  } catch (err) {
    setDraftAlert(`❌ Network Error: Failed to reach backend (${err.message}).`, 'error');
    showToast(`Network Error: ${err.message}`, 'error');
  } finally {
    if (btnSave) btnSave.disabled = false;
    if (spinSave) spinSave.style.display = 'none';
  }
}

function copyDraftSubject() {
  const subject = document.getElementById('draft-subject-input')?.value || '';
  if (!subject) {
    showToast('No subject to copy', 'error');
    return;
  }
  copyText(subject, 'Subject copied');
}

function copyDraftBody() {
  const body = document.getElementById('draft-body-textarea')?.value || '';
  if (!body) {
    showToast('No email body to copy', 'error');
    return;
  }
  copyText(body, 'Email body copied');
}

function copyDraftFull() {
  const subject = document.getElementById('draft-subject-input')?.value || '';
  const body = document.getElementById('draft-body-textarea')?.value || '';
  if (!subject && !body) {
    showToast('No draft content to copy', 'error');
    return;
  }
  const fullText = `Subject: ${subject}\n\n${body}`;
  copyText(fullText, 'Full email copied');
}

