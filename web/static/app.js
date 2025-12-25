// Базовый JavaScript для админ-панели

const API_BASE = '/api';

// ----------------- UX helpers (toasts + global loader) -----------------
let _loadingCount = 0;

function ensureUiScaffolding() {
    if (!document.getElementById('toast-container')) {
        const tc = document.createElement('div');
        tc.id = 'toast-container';
        document.body.appendChild(tc);
    }
    if (!document.getElementById('global-loading')) {
        const gl = document.createElement('div');
        gl.id = 'global-loading';
        gl.innerHTML = `
            <div class="d-flex flex-column align-items-center">
                <div class="spinner-border text-primary" role="status" aria-label="Загрузка..."></div>
                <div class="mt-2 text-muted">Загрузка...</div>
            </div>
        `;
        document.body.appendChild(gl);
    }
}

function setGlobalLoading(isLoading) {
    const el = document.getElementById('global-loading');
    if (!el) return;
    if (isLoading) {
        _loadingCount++;
    } else {
        _loadingCount = Math.max(0, _loadingCount - 1);
    }
    el.style.display = _loadingCount > 0 ? 'flex' : 'none';
}

function showToast({ variant = 'primary', title = 'Сообщение', message = '' }) {
    ensureUiScaffolding();
    const container = document.getElementById('toast-container');
    const id = `toast_${Date.now()}_${Math.floor(Math.random() * 100000)}`;

    const html = `
        <div id="${id}" class="toast align-items-center text-bg-${variant} border-0 mb-2" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="d-flex">
                <div class="toast-body">
                    <strong class="me-2">${escapeHtml(title)}</strong>
                    <span>${escapeHtml(message)}</span>
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Закрыть"></button>
            </div>
        </div>
    `;
    container.insertAdjacentHTML('beforeend', html);
    const toastEl = document.getElementById(id);
    const bsToast = new bootstrap.Toast(toastEl, { delay: 3500 });
    bsToast.show();
    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
}

function toastSuccess(message, title = 'Готово') {
    showToast({ variant: 'success', title, message });
}

function toastError(message, title = 'Ошибка') {
    showToast({ variant: 'danger', title, message });
}

async function apiAction(endpoint, options = {}, { successMessage = null } = {}) {
    try {
        setGlobalLoading(true);
        const data = await apiFetch(endpoint, options);
        if (successMessage) toastSuccess(successMessage);
        return data;
    } catch (e) {
        toastError(e.message || 'Ошибка запроса');
        throw e;
    } finally {
        setGlobalLoading(false);
    }
}

// Получение токена авторизации (Basic Auth)
function getAuthHeaders() {
    // В реальном приложении здесь должна быть логика получения токена
    return {
        'Content-Type': 'application/json'
    };
}

// Базовый fetch с авторизацией
async function apiFetch(endpoint, options = {}) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
        ...options,
        headers: {
            ...getAuthHeaders(),
            ...options.headers
        },
        credentials: 'include'
    });
    
    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(error.detail || 'Ошибка запроса');
    }
    
    return response.json();
}

// Навигация
document.addEventListener('DOMContentLoaded', () => {
    ensureUiScaffolding();
    const navItems = document.querySelectorAll('[data-page]');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const page = item.dataset.page;
            loadPage(page);
            
            // Обновляем активный элемент
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');
        });
    });
    
    // Загружаем дашборд по умолчанию
    loadPage('dashboard');
});

// Загрузка страницы
async function loadPage(page) {
    const content = document.getElementById('content');
    content.innerHTML = '<div class="loading">Загрузка...</div>';
    
    try {
        switch(page) {
            case 'dashboard':
                await loadDashboard();
                break;
            case 'tickets':
                await loadTickets();
                break;
            case 'users':
                await loadUsers();
                break;
            case 'quiz':
                await loadQuiz();
                break;
            case 'raffle':
                await loadRaffle();
                break;
            case 'dice':
                await loadDice();
                break;
            case 'stats':
                await loadStats();
                break;
            case 'scheduler':
                await loadScheduler();
                break;
            default:
                content.innerHTML = '<div class="alert alert-warning">Страница не найдена</div>';
        }
    } catch (error) {
        content.innerHTML = `<div class="alert alert-danger">Ошибка: ${error.message}</div>`;
    }
}

// Дашборд
async function loadDashboard() {
    const [systemStats, dailyReport, newUsers] = await Promise.all([
        apiFetch('/stats/system'),
        apiFetch('/stats/daily'),
        apiFetch('/users/new?days=1&limit=20')
    ]);
    
    const content = document.getElementById('content');
    
    let newUsersHtml = '';
    if (newUsers.users && newUsers.users.length > 0) {
        newUsersHtml = `
            <div class="card mt-4">
                <div class="card-header">
                    <h5>🆕 Новые пользователи за сегодня (${newUsers.users.length})</h5>
                </div>
                <div class="card-body">
                    <div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
                        <table class="table table-sm">
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Username</th>
                                    <th>Имя</th>
                                    <th>Знак</th>
                                    <th>Время регистрации</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${newUsers.users.map(user => `
                                    <tr>
                                        <td>${user.id}</td>
                                        <td>${user.username || '-'}</td>
                                        <td>${user.first_name || '-'}</td>
                                        <td>${user.zodiac_name || user.zodiac || '-'}</td>
                                        <td>${user.created_at ? new Date(user.created_at).toLocaleString('ru-RU') : '-'}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;
    }
    
    content.innerHTML = `
        <h2>📊 Дашборд</h2>
        
        <div class="row mt-4">
            <div class="col-md-4">
                <div class="card stat-card success">
                    <h5>👥 Пользователи</h5>
                    <h3>${systemStats.users.total}</h3>
                    <p>Подписанных: ${systemStats.users.subscribed}</p>
                    <p>Активных за 24ч: ${systemStats.users.active_24h}</p>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card stat-card">
                    <h5>🎟 Билетики</h5>
                    <h3>${systemStats.tickets.total}</h3>
                    <p>Из квизов: ${systemStats.tickets.from_quiz}</p>
                    <p>Из розыгрышей: ${systemStats.tickets.from_raffle}</p>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card stat-card warning">
                    <h5>📅 Сегодня</h5>
                    <h3>${dailyReport.new_users}</h3>
                    <p>Новых пользователей</p>
                    <p>Билетиков: ${dailyReport.tickets.total}</p>
                </div>
            </div>
        </div>
        ${newUsersHtml}
    `;
}



// Квизы
async function loadQuiz() {
    const [quizListData, disabledDates] = await Promise.all([
        apiFetch('/quiz/list'),
        apiFetch('/quiz/disabled-dates')
    ]);
    
    const disabledSet = new Set(disabledDates.disabled_dates || []);
    
    const content = document.getElementById('content');
    content.innerHTML = `
        <h2>🎯 Квизы</h2>
        <div class="card mb-3">
            <div class="card-body">
                <div class="input-group">
                    <span class="input-group-text">🔎</span>
                    <input type="text" class="form-control" id="quizSearch" placeholder="Поиск по дате или заголовку...">
                </div>
            </div>
        </div>
        <div class="list-group" id="quiz-list">
            ${(quizListData.quizzes || []).map(item => {
                const date = item.quiz_date;
                const title = item.title ? ` — <span class="text-muted">${escapeHtml(item.title)}</span>` : '';
                const startsAt = item.starts_at_msk ? `<small class="text-muted">(${escapeHtml(item.starts_at_msk)} МСК)</small>` : '';
                const isDisabled = disabledSet.has(date);
                return `
                    <div class="list-group-item d-flex justify-content-between align-items-center" data-quiz-item="1" data-quiz-date="${escapeHtml(date)}" data-quiz-title="${escapeHtml(item.title || '')}">
                        <a href="#" class="flex-grow-1 text-decoration-none quiz-date-link" data-quiz-date="${date}">
                            <div>
                                <strong>${date}</strong>${title}
                                ${isDisabled ? '<span class="badge bg-danger ms-2">Отключен</span>' : ''}
                            </div>
                            <div>${startsAt}</div>
                        </a>
                        <div>
                            <button class="btn btn-sm ${isDisabled ? 'btn-success' : 'btn-warning'}" onclick="event.stopPropagation(); toggleQuizDate('${date}'); return false;">
                                ${isDisabled ? '✅ Включить' : '⏸️ Отключить'}
                            </button>
                            <button class="btn btn-sm btn-danger ms-1" onclick="event.stopPropagation(); deleteQuiz('${date}'); return false;">
                                🗑 Удалить
                            </button>
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
        <div class="mt-3">
            <button class="btn btn-success" onclick="showCreateQuizForm()">➕ Добавить квиз</button>
        </div>
    `;
    
    // Обработчики для дат квизов (используем делегирование событий)
    const quizListEl = document.getElementById('quiz-list');
    if (quizListEl) {
        quizListEl.addEventListener('click', async (e) => {
            const link = e.target.closest('.quiz-date-link');
            if (link) {
                e.preventDefault();
                e.stopPropagation();
                const quizDate = link.dataset.quizDate;
                await showQuizDetails(quizDate);
            }
        });
    }

    const searchEl = document.getElementById('quizSearch');
    if (searchEl) {
        searchEl.addEventListener('input', () => {
            const q = (searchEl.value || '').trim().toLowerCase();
            const items = document.querySelectorAll('[data-quiz-item="1"]');
            items.forEach(it => {
                const d = (it.getAttribute('data-quiz-date') || '').toLowerCase();
                const t = (it.getAttribute('data-quiz-title') || '').toLowerCase();
                const ok = !q || d.includes(q) || t.includes(q);
                it.style.display = ok ? '' : 'none';
            });
        });
    }
}

async function showQuizDetails(quizDate) {
    try {
        const [meta, stats, questions] = await Promise.all([
            apiFetch(`/quiz/${quizDate}/meta`),
            apiFetch(`/quiz/${quizDate}/stats`),
            apiFetch(`/quiz/${quizDate}/questions`)
        ]);
        
        const content = document.getElementById('content');
        const title = meta.title ? ` — ${escapeHtml(meta.title)}` : '';
        const startsAt = meta.starts_at_msk ? `<p class="text-muted mb-1">🕒 Начало: <strong>${escapeHtml(meta.starts_at_msk)}</strong> МСК</p>` : '';
        
        let questionsHtml = '<p>Вопросы не найдены</p>';
        if (questions.questions && questions.questions.length > 0) {
            questionsHtml = questions.questions.map((q, idx) => {
                const questionId = q.id || (idx + 1);
                const questionText = q.question || q.question_text || 'Нет текста';
                const options = q.options || [];
                const correctAnswer = q.correct_answer !== undefined ? q.correct_answer : (q.correct !== undefined ? q.correct : null);
                
                let optionsHtml = '';
                if (options.length > 0) {
                    if (typeof options === 'object' && !Array.isArray(options)) {
                        // Если options - это объект типа {"A": "...", "Б": "..."}
                        const optionKeys = Object.keys(options);
                        optionsHtml = `
                            <ul>
                                ${optionKeys.map((key, i) => `
                                    <li>${key}. ${options[key]} ${key === correctAnswer ? '✅' : ''}</li>
                                `).join('')}
                            </ul>
                        `;
                    } else {
                        // Если options - это массив
                        optionsHtml = `
                            <ul>
                                ${options.map((opt, i) => `
                                    <li>${i + 1}. ${opt} ${i === correctAnswer ? '✅' : ''}</li>
                                `).join('')}
                            </ul>
                        `;
                    }
                }
                
                return `
                    <div class="card mb-2">
                        <div class="card-body">
                            <div class="d-flex justify-content-between align-items-start">
                                <div class="flex-grow-1">
                                    <h6>Вопрос #${questionId}</h6>
                                    <p><strong>${questionText}</strong></p>
                                    ${optionsHtml}
                                </div>
                                <div>
                                    <button class="btn btn-sm btn-danger" onclick="removeQuizQuestion('${quizDate}', ${questionId})">🗑 Удалить</button>
                                </div>
                            </div>
                            <button class="btn btn-sm btn-primary mt-2" onclick="editQuizQuestion('${quizDate}', ${questionId})">✏️ Редактировать</button>
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        content.innerHTML = `
            <h2>🎯 Квиз ${quizDate}${title}</h2>
            <button class="btn btn-secondary mb-3" onclick="loadQuiz()">◀️ Назад к списку</button>
            <div class="btn-group mb-3" role="group">
                <button class="btn btn-outline-primary" onclick="editQuizMeta('${quizDate}')">✏️ Мета</button>
                <button class="btn btn-outline-secondary" onclick="duplicateQuiz('${quizDate}')">📋 Дублировать</button>
                <button class="btn btn-outline-info" onclick="previewQuiz('${quizDate}')">👀 Превью</button>
                <button class="btn btn-outline-dark" onclick="rescheduleQuizJobs('${quizDate}')">🔁 Перепланировать</button>
            </div>
            
            <div class="card mb-3">
                <div class="card-body">
                    <h5>Статистика</h5>
                    ${startsAt}
                    <p>Всего участников: ${stats.total_participants || 0}</p>
                    <p>Получили билетик: ${stats.with_tickets || 0}</p>
                    <p>Не получили билетик: ${stats.no_tickets || 0}</p>
                    <p>Не приняли участие: ${stats.non_participants || 0}</p>
                </div>
            </div>
            
            <div class="d-flex justify-content-between align-items-center mb-2">
                <h5>Вопросы</h5>
                <button class="btn btn-outline-primary btn-sm" onclick="showAddQuizQuestionForm('${quizDate}')">➕ Добавить вопрос</button>
            </div>
            ${questionsHtml}
        `;
    } catch (error) {
        const content = document.getElementById('content');
        content.innerHTML = `
            <h2>🎯 Квиз ${quizDate}</h2>
            <button class="btn btn-secondary mb-3" onclick="loadQuiz()">◀️ Назад к списку</button>
            <div class="alert alert-danger">
                Ошибка при загрузке данных: ${error.message}
            </div>
        `;
    }
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function isoToDatetimeLocalMsk(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const parts = new Intl.DateTimeFormat('ru-RU', {
        timeZone: 'Europe/Moscow',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23'
    }).formatToParts(d);
    const get = (t) => parts.find(p => p.type === t)?.value;
    const y = get('year');
    const m = get('month');
    const day = get('day');
    const h = get('hour');
    const min = get('minute');
    if (!y || !m || !day || !h || !min) return '';
    return `${y}-${m}-${day}T${h}:${min}`;
}

function isoToHumanMsk(iso) {
    if (!iso) return '-';
    try {
        return new Date(iso).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' });
    } catch {
        return iso;
    }
}

async function rescheduleQuizJobs(quizDate) {
    try {
        const resp = await apiAction(`/scheduler/quiz/${quizDate}/reschedule`, { method: 'POST' });
        toastSuccess(resp.rescheduled ? 'Задачи пересозданы' : 'Scheduler не запущен (задачи обновятся при рестарте)');
    } catch (e) {
        // toast already
    }
}

async function editQuizMeta(quizDate) {
    try {
        const meta = await apiFetch(`/quiz/${quizDate}/meta`);
        const currentTitle = meta.title || '';
        const currentStartsAtLocal = isoToDatetimeLocalMsk(meta.starts_at);

        const modalHtml = `
            <div class="modal fade" id="editQuizMetaModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">✏️ Мета квиза ${escapeHtml(quizDate)}</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <form id="editQuizMetaForm">
                                <div class="mb-3">
                                    <label class="form-label">Дата и время старта (МСК)</label>
                                    <input type="datetime-local" class="form-control" id="eqmStartsAt" value="${escapeHtml(currentStartsAtLocal)}" required>
                                    <div class="form-text">Должно оставаться в дате ${escapeHtml(quizDate)}. Для переноса используйте «Дублировать».</div>
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">Заголовок</label>
                                    <input type="text" class="form-control" id="eqmTitle" value="${escapeHtml(currentTitle)}" required>
                                </div>
                            </form>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Отмена</button>
                            <button type="button" class="btn btn-primary" onclick="saveQuizMeta('${quizDate}')">💾 Сохранить</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const existing = document.getElementById('editQuizMetaModal');
        if (existing) existing.remove();
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        const bsModal = new bootstrap.Modal(document.getElementById('editQuizMetaModal'));
        bsModal.show();
        document.getElementById('editQuizMetaModal').addEventListener('hidden.bs.modal', function() {
            this.remove();
        });
    } catch (e) {
        toastError(e.message || 'Не удалось загрузить метаданные');
    }
}

async function saveQuizMeta(quizDate) {
    const form = document.getElementById('editQuizMetaForm');
    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }
    const startsAt = document.getElementById('eqmStartsAt').value;
    const title = document.getElementById('eqmTitle').value.trim();
    try {
        const resp = await apiAction(`/quiz/${quizDate}/meta`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ starts_at_local: startsAt, title })
        });
        toastSuccess(resp.scheduled ? 'Мета обновлена, scheduler автоматически обновлен' : 'Мета обновлена (scheduler не запущен)');
        const modal = bootstrap.Modal.getInstance(document.getElementById('editQuizMetaModal'));
        if (modal) modal.hide();
        await showQuizDetails(quizDate);
    } catch (e) {
        // toast already
    }
}

async function duplicateQuiz(quizDate) {
    try {
        const meta = await apiFetch(`/quiz/${quizDate}/meta`);
        const currentTitle = meta.title || '';
        const defaultTitle = currentTitle ? `${currentTitle} (копия)` : 'Квиз (копия)';

        const modalHtml = `
            <div class="modal fade" id="duplicateQuizModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">📋 Дублировать квиз ${escapeHtml(quizDate)}</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <form id="duplicateQuizForm">
                                <div class="mb-3">
                                    <label class="form-label">Новая дата и время (МСК)</label>
                                    <input type="datetime-local" class="form-control" id="dqStartsAt" required>
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">Заголовок</label>
                                    <input type="text" class="form-control" id="dqTitle" value="${escapeHtml(defaultTitle)}" required>
                                </div>
                            </form>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Отмена</button>
                            <button type="button" class="btn btn-primary" onclick="saveDuplicateQuiz('${quizDate}')">💾 Создать копию</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const existing = document.getElementById('duplicateQuizModal');
        if (existing) existing.remove();
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        const bsModal = new bootstrap.Modal(document.getElementById('duplicateQuizModal'));
        bsModal.show();
        document.getElementById('duplicateQuizModal').addEventListener('hidden.bs.modal', function() {
            this.remove();
        });
    } catch (e) {
        toastError(e.message || 'Не удалось открыть форму дублирования');
    }
}

async function saveDuplicateQuiz(sourceQuizDate) {
    const form = document.getElementById('duplicateQuizForm');
    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }
    const startsAt = document.getElementById('dqStartsAt').value;
    const title = document.getElementById('dqTitle').value.trim();
    try {
        const resp = await apiAction(`/quiz/duplicate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_quiz_date: sourceQuizDate, starts_at_local: startsAt, title })
        });
        toastSuccess(`Квиз продублирован на дату ${resp.quiz_date}${resp.scheduled ? ' (задачи обновлены)' : ''}`);
        const modal = bootstrap.Modal.getInstance(document.getElementById('duplicateQuizModal'));
        if (modal) modal.hide();
        await showQuizDetails(resp.quiz_date);
    } catch (e) {
        // toast already
    }
}

async function previewQuiz(quizDate) {
    try {
        const [meta, questions] = await Promise.all([
            apiFetch(`/quiz/${quizDate}/meta`),
            apiFetch(`/quiz/${quizDate}/questions`)
        ]);
        const title = meta.title ? `<div class="text-muted mb-2">${escapeHtml(meta.title)}</div>` : '';
        const starts = meta.starts_at ? `<div class="text-muted mb-2">🕒 ${escapeHtml(isoToHumanMsk(meta.starts_at))} (МСК)</div>` : '';
        const qCount = (questions.questions || []).length;
        const first = (questions.questions || [])[0];

        let firstHtml = '<div class="text-muted">Нет вопросов</div>';
        if (first) {
            const qText = escapeHtml(first.question || first.question_text || '');
            const opts = first.options || {};
            const keys = typeof opts === 'object' && !Array.isArray(opts) ? Object.keys(opts) : [];
            const optsHtml = keys.length
                ? `<ul class="mb-0">${keys.map(k => `<li>${escapeHtml(k)}. ${escapeHtml(opts[k])}</li>`).join('')}</ul>`
                : '';
            firstHtml = `
                <div class="card">
                    <div class="card-body">
                        <div class="fw-bold mb-2">${qText}</div>
                        ${optsHtml}
                    </div>
                </div>
            `;
        }

        const modalHtml = `
            <div class="modal fade" id="previewQuizModal" tabindex="-1">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">👀 Превью квиза ${escapeHtml(quizDate)}</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            ${title}
                            ${starts}
                            <div class="mb-3">
                                <div class="fw-bold">Текст объявления (как увидит пользователь)</div>
                                <div class="border rounded p-3 bg-light">
                                    <div class="fw-bold">🎯 Квиз начинается!</div>
                                    ${meta.title ? `<div class="mt-1">${escapeHtml(meta.title)}</div>` : ''}
                                    <div class="mt-2">Нажми на кнопку ниже, чтобы принять участие.<br>У тебя есть 6 часов, чтобы начать квиз!</div>
                                </div>
                            </div>
                            <div class="mb-2 fw-bold">Первый вопрос (пример)</div>
                            ${firstHtml}
                            <div class="text-muted mt-3">Всего вопросов: ${qCount}</div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Закрыть</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const existing = document.getElementById('previewQuizModal');
        if (existing) existing.remove();
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        const bsModal = new bootstrap.Modal(document.getElementById('previewQuizModal'));
        bsModal.show();
        document.getElementById('previewQuizModal').addEventListener('hidden.bs.modal', function() {
            this.remove();
        });
    } catch (e) {
        toastError(e.message || 'Не удалось построить превью');
    }
}

function showCreateQuizForm() {
    const content = document.getElementById('content');
    content.innerHTML = `
        <h2>➕ Добавить квиз</h2>
        <button class="btn btn-secondary mb-3" onclick="loadQuiz()">◀️ Назад к списку</button>

        <div class="card">
            <div class="card-body">
                <form id="createQuizForm">
                    <div class="mb-3">
                        <label class="form-label">Дата и время квиза (МСК)</label>
                        <input type="datetime-local" class="form-control" id="cqStartsAt" required>
                        <div class="form-text">Ввод интерпретируется как московское время.</div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Заголовок квиза</label>
                        <input type="text" class="form-control" id="cqTitle" required>
                    </div>

                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <h5 class="mb-0">Вопросы</h5>
                        <button type="button" class="btn btn-outline-primary btn-sm" onclick="addCreateQuizQuestion()">➕ Добавить вопрос</button>
                    </div>

                    <div id="cqQuestions"></div>

                    <div class="mt-3">
                        <button type="submit" class="btn btn-success">💾 Создать квиз</button>
                    </div>
                </form>
            </div>
        </div>
    `;

    // Стартуем минимум с 1 вопроса
    window._cqCounter = 0;
    addCreateQuizQuestion();

    const form = document.getElementById('createQuizForm');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await submitCreateQuiz();
    });
}

function addCreateQuizQuestion() {
    const container = document.getElementById('cqQuestions');
    if (!container) return;
    const id = (++window._cqCounter);
    const block = document.createElement('div');
    block.className = 'card mb-3';
    block.setAttribute('data-cq-id', String(id));
    block.innerHTML = `
        <div class="card-body">
            <div class="d-flex justify-content-between align-items-center">
                <h6 class="mb-2">Вопрос #${id}</h6>
                <button type="button" class="btn btn-outline-danger btn-sm" onclick="removeCreateQuizQuestion(${id})">🗑 Удалить</button>
            </div>
            <div class="mb-2">
                <label class="form-label">Текст вопроса</label>
                <textarea class="form-control" id="cqQ_${id}" rows="2" required></textarea>
            </div>
            <div class="mb-2">
                <label class="form-label">Варианты ответов (1-4)</label>
                <div class="input-group mb-2">
                    <span class="input-group-text">1</span>
                    <input type="text" class="form-control" id="cqO_${id}_1" required>
                </div>
                <div class="input-group mb-2">
                    <span class="input-group-text">2</span>
                    <input type="text" class="form-control" id="cqO_${id}_2" required>
                </div>
                <div class="input-group mb-2">
                    <span class="input-group-text">3</span>
                    <input type="text" class="form-control" id="cqO_${id}_3" required>
                </div>
                <div class="input-group mb-2">
                    <span class="input-group-text">4</span>
                    <input type="text" class="form-control" id="cqO_${id}_4" required>
                </div>
            </div>
            <div class="mb-2">
                <label class="form-label">Правильный ответ</label>
                <select class="form-select" id="cqC_${id}" required>
                    <option value="1">1</option>
                    <option value="2">2</option>
                    <option value="3">3</option>
                    <option value="4">4</option>
                </select>
            </div>
        </div>
    `;
    container.appendChild(block);
    _ensureCreateQuizRemoveButtons();
}

function removeCreateQuizQuestion(id) {
    const container = document.getElementById('cqQuestions');
    if (!container) return;
    const blocks = container.querySelectorAll('[data-cq-id]');
    if (blocks.length <= 1) {
        alert('Должен быть минимум 1 вопрос');
        return;
    }
    const el = container.querySelector(`[data-cq-id="${id}"]`);
    if (el) el.remove();
    _ensureCreateQuizRemoveButtons();
}

function _ensureCreateQuizRemoveButtons() {
    const container = document.getElementById('cqQuestions');
    if (!container) return;
    const blocks = container.querySelectorAll('[data-cq-id]');
    const disableRemove = blocks.length <= 1;
    blocks.forEach(b => {
        const btn = b.querySelector('button.btn-outline-danger');
        if (btn) btn.disabled = disableRemove;
    });
}

async function submitCreateQuiz() {
    const startsAt = document.getElementById('cqStartsAt').value;
    const title = document.getElementById('cqTitle').value.trim();
    if (!startsAt) {
        alert('Выберите дату и время квиза');
        return;
    }
    if (!title) {
        alert('Введите заголовок квиза');
        return;
    }

    const container = document.getElementById('cqQuestions');
    const blocks = Array.from(container.querySelectorAll('[data-cq-id]'));
    if (blocks.length < 1) {
        alert('Добавьте минимум 1 вопрос');
        return;
    }

    const questions = blocks.map((b) => {
        const id = b.getAttribute('data-cq-id');
        const question = document.getElementById(`cqQ_${id}`).value.trim();
        const options = {
            "1": document.getElementById(`cqO_${id}_1`).value.trim(),
            "2": document.getElementById(`cqO_${id}_2`).value.trim(),
            "3": document.getElementById(`cqO_${id}_3`).value.trim(),
            "4": document.getElementById(`cqO_${id}_4`).value.trim()
        };
        const correct_answer = document.getElementById(`cqC_${id}`).value;
        return { question, options, correct_answer };
    });

    // Простая валидация
    for (let i = 0; i < questions.length; i++) {
        const q = questions[i];
        if (!q.question) {
            toastError(`Вопрос #${i + 1}: пустой текст`);
            return;
        }
        for (const k of ["1","2","3","4"]) {
            if (!q.options[k]) {
                toastError(`Вопрос #${i + 1}: вариант ${k} обязателен`);
                return;
            }
        }
        if (!["1","2","3","4"].includes(q.correct_answer)) {
            toastError(`Вопрос #${i + 1}: выберите правильный ответ`);
            return;
        }
    }

    try {
        const resp = await apiAction('/quiz/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                starts_at_local: startsAt,
                title,
                questions
            })
        });
        toastSuccess(`Квиз создан на дату ${resp.quiz_date}${resp.scheduled ? ' (задачи обновлены)' : ''}`);
        await loadQuiz();
    } catch (error) {
        // toast уже показан в apiAction
    }
}

async function toggleQuizDate(quizDate) {
    try {
        const result = await apiAction(`/quiz/${quizDate}/toggle`, { method: 'POST' });
        toastSuccess(result.message || 'Сохранено');
        loadQuiz();
    } catch (error) {
        // toast уже показан в apiAction
    }
}

async function deleteQuiz(quizDate) {
    if (!confirm(`Удалить квиз ${quizDate}? Это действие нельзя отменить.`)) {
        return;
    }
    try {
        await apiAction(`/quiz/${quizDate}`, { method: 'DELETE' });
        toastSuccess('Квиз удален');
        loadQuiz();
    } catch (e) {
        // toast already
    }
}

async function editQuizQuestion(quizDate, questionId) {
    try {
        // Получаем данные вопроса
        const questionsData = await apiFetch(`/quiz/${quizDate}/questions`);
        const question = questionsData.questions.find(q => q.id === questionId || q.id === parseInt(questionId));
        
        if (!question) {
            toastError('Вопрос не найден');
            return;
        }
        
        // Подготавливаем данные для формы
        const questionText = (question.question || question.question_text || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        const options = question.options || {};
        
        // Преобразуем options в массив, если это объект
        let optionsArray = [];
        if (typeof options === 'object' && !Array.isArray(options)) {
            // Если это объект с ключами "1", "2", "3", "4"
            const keys = Object.keys(options).sort();
            optionsArray = keys.map(key => ({
                key: key,
                value: String(options[key] || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
            }));
        } else if (Array.isArray(options)) {
            optionsArray = options.map((opt, idx) => ({
                key: String(idx + 1),
                value: String(opt || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
            }));
        } else {
            // Если options нет, создаем пустые
            optionsArray = [
                { key: '1', value: '' },
                { key: '2', value: '' },
                { key: '3', value: '' },
                { key: '4', value: '' }
            ];
        }
        
        // Заполняем до 4 вариантов
        while (optionsArray.length < 4) {
            optionsArray.push({ key: String(optionsArray.length + 1), value: '' });
        }
        
        const correctAnswer = String(question.correct_answer || question.correct || '1');
        
        // Создаем модальное окно
        const modalHtml = `
            <div class="modal fade" id="editQuizQuestionModal" tabindex="-1">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">✏️ Редактирование вопроса #${questionId}</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <form id="editQuizQuestionForm">
                                <div class="mb-3">
                                    <label for="questionText" class="form-label">Текст вопроса</label>
                                    <textarea class="form-control" id="questionText" rows="3" required>${questionText}</textarea>
                                </div>
                                
                                <div class="mb-3">
                                    <label class="form-label">Варианты ответов</label>
                                    ${optionsArray.map((opt, idx) => `
                                        <div class="input-group mb-2">
                                            <span class="input-group-text">${opt.key}</span>
                                            <input type="text" class="form-control option-input" 
                                                   data-key="${opt.key}" 
                                                   value="${opt.value}" 
                                                   placeholder="Вариант ответа ${opt.key}" required>
                                        </div>
                                    `).join('')}
                                </div>
                                
                                <div class="mb-3">
                                    <label class="form-label">Правильный ответ</label>
                                    <select class="form-select" id="correctAnswer" required>
                                        ${optionsArray.map(opt => `
                                            <option value="${opt.key}" ${opt.key === correctAnswer ? 'selected' : ''}>
                                                ${opt.key}
                                            </option>
                                        `).join('')}
                                    </select>
                                </div>
                            </form>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Отмена</button>
                            <button type="button" class="btn btn-primary" onclick="saveQuizQuestion('${quizDate}', ${questionId})">💾 Сохранить</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Удаляем предыдущее модальное окно, если есть
        const existingModal = document.getElementById('editQuizQuestionModal');
        if (existingModal) {
            existingModal.remove();
        }
        
        // Добавляем новое модальное окно
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        const bsModal = new bootstrap.Modal(document.getElementById('editQuizQuestionModal'));
        bsModal.show();
        
        // Удаляем модальное окно после закрытия
        document.getElementById('editQuizQuestionModal').addEventListener('hidden.bs.modal', function() {
            this.remove();
        });
    } catch (error) {
        alert('Ошибка при загрузке вопроса: ' + error.message);
    }
}

async function saveQuizQuestion(quizDate, questionId) {
    try {
        const form = document.getElementById('editQuizQuestionForm');
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }
        
        const questionText = document.getElementById('questionText').value.trim();
        if (!questionText) {
            alert('Введите текст вопроса');
            return;
        }
        
        // Собираем варианты ответов
        const optionInputs = document.querySelectorAll('.option-input');
        const options = {};
        optionInputs.forEach(input => {
            const key = input.dataset.key;
            const value = input.value.trim();
            if (value) {
                options[key] = value;
            }
        });
        
        if (Object.keys(options).length === 0) {
            alert('Введите хотя бы один вариант ответа');
            return;
        }
        
        const correctAnswer = document.getElementById('correctAnswer').value;
        if (!options[correctAnswer]) {
            alert('Правильный ответ должен быть одним из вариантов');
            return;
        }
        
        // Отправляем данные на сервер
        const response = await apiAction(`/quiz/${quizDate}/questions/${questionId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                question_text: questionText,
                options: options,
                correct_answer: correctAnswer
            })
        });
        
        if (response.success) {
            // Закрываем модальное окно
            const modal = bootstrap.Modal.getInstance(document.getElementById('editQuizQuestionModal'));
            if (modal) {
                modal.hide();
            }
            
            // Обновляем отображение квиза
            await showQuizDetails(quizDate);
            
            toastSuccess(response.scheduled ? 'Вопрос обновлен, scheduler обновлен' : 'Вопрос обновлен');
        } else {
            toastError(response.message || 'Не удалось сохранить вопрос');
        }
    } catch (error) {
        toastError('Ошибка при сохранении: ' + error.message);
    }
}

async function removeQuizQuestion(quizDate, questionId) {
    if (!confirm(`Удалить вопрос #${questionId}?`)) {
        return;
    }
    try {
        const response = await apiAction(`/quiz/${quizDate}/questions/${questionId}`, { method: 'DELETE' });
        toastSuccess(response.scheduled ? 'Вопрос удален, scheduler обновлен' : 'Вопрос удален');
        await showQuizDetails(quizDate);
    } catch (e) {
        // toast already
    }
}

function showAddQuizQuestionForm(quizDate) {
    const modalHtml = `
        <div class="modal fade" id="addQuizQuestionModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">➕ Добавить вопрос</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <form id="addQuizQuestionForm">
                            <div class="mb-3">
                                <label class="form-label">ID вопроса</label>
                                <input type="number" class="form-control" id="aqqId" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Текст вопроса</label>
                                <textarea class="form-control" id="aqqText" rows="3" required></textarea>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Варианты ответов</label>
                                <div class="input-group mb-2">
                                    <span class="input-group-text">1</span>
                                    <input type="text" class="form-control" id="aqqO1" required>
                                </div>
                                <div class="input-group mb-2">
                                    <span class="input-group-text">2</span>
                                    <input type="text" class="form-control" id="aqqO2" required>
                                </div>
                                <div class="input-group mb-2">
                                    <span class="input-group-text">3</span>
                                    <input type="text" class="form-control" id="aqqO3" required>
                                </div>
                                <div class="input-group mb-2">
                                    <span class="input-group-text">4</span>
                                    <input type="text" class="form-control" id="aqqO4" required>
                                </div>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Правильный ответ</label>
                                <select class="form-select" id="aqqCorrect" required>
                                    <option value="1">1</option>
                                    <option value="2">2</option>
                                    <option value="3">3</option>
                                    <option value="4">4</option>
                                </select>
                            </div>
                        </form>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Отмена</button>
                        <button type="button" class="btn btn-primary" onclick="saveAddQuizQuestion('${quizDate}')">💾 Добавить</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    const existing = document.getElementById('addQuizQuestionModal');
    if (existing) existing.remove();
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    const bsModal = new bootstrap.Modal(document.getElementById('addQuizQuestionModal'));
    bsModal.show();
    document.getElementById('addQuizQuestionModal').addEventListener('hidden.bs.modal', function() {
        this.remove();
    });
}

async function saveAddQuizQuestion(quizDate) {
    const form = document.getElementById('addQuizQuestionForm');
    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }
    const questionId = parseInt(document.getElementById('aqqId').value);
    const questionText = document.getElementById('aqqText').value.trim();
    const options = {
        "1": document.getElementById('aqqO1').value.trim(),
        "2": document.getElementById('aqqO2').value.trim(),
        "3": document.getElementById('aqqO3').value.trim(),
        "4": document.getElementById('aqqO4').value.trim()
    };
    const correctAnswer = document.getElementById('aqqCorrect').value;
    
    try {
        const response = await apiAction(`/quiz/${quizDate}/questions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question_id: questionId,
                question_text: questionText,
                options: options,
                correct_answer: correctAnswer
            })
        });
        const modal = bootstrap.Modal.getInstance(document.getElementById('addQuizQuestionModal'));
        if (modal) modal.hide();
        toastSuccess(response.scheduled ? 'Вопрос добавлен, scheduler обновлен' : 'Вопрос добавлен');
        await showQuizDetails(quizDate);
    } catch (e) {
        // toast already
    }
}

// Розыгрыши
async function loadRaffle() {
    const [raffleListData, disabledDates] = await Promise.all([
        apiFetch('/raffle/list'),
        apiFetch('/raffle/disabled-dates')
    ]);
    
    const disabledSet = new Set(disabledDates.disabled_dates || []);
    
    const content = document.getElementById('content');
    content.innerHTML = `
        <h2>🎁 Розыгрыши</h2>
        <div class="card mb-3">
            <div class="card-body">
                <div class="input-group">
                    <span class="input-group-text">🔎</span>
                    <input type="text" class="form-control" id="raffleSearch" placeholder="Поиск по дате или заголовку...">
                </div>
            </div>
        </div>
        <div class="list-group" id="raffle-list">
            ${(raffleListData.raffles || []).map(item => {
                const date = item.raffle_date;
                const title = item.title ? ` — <span class="text-muted">${escapeHtml(item.title)}</span>` : '';
                const startsAt = item.starts_at_msk ? `<small class="text-muted">(${escapeHtml(item.starts_at_msk)} МСК)</small>` : '';
                const isDisabled = disabledSet.has(date);
                return `
                    <div class="list-group-item d-flex justify-content-between align-items-center" data-raffle-item="1" data-raffle-date="${escapeHtml(date)}" data-raffle-title="${escapeHtml(item.title || '')}">
                        <a href="#" class="flex-grow-1 text-decoration-none raffle-date-link" data-raffle-date="${date}">
                            <div>
                                <strong>${date}</strong>${title}
                                ${isDisabled ? '<span class="badge bg-danger ms-2">Отключен</span>' : ''}
                            </div>
                            <div>${startsAt}</div>
                        </a>
                        <div>
                            <button class="btn btn-sm ${isDisabled ? 'btn-success' : 'btn-warning'}" onclick="event.stopPropagation(); toggleRaffleDate('${date}'); return false;">
                                ${isDisabled ? '✅ Включить' : '⏸️ Отключить'}
                            </button>
                            <button class="btn btn-sm btn-danger ms-1" onclick="event.stopPropagation(); deleteRaffle('${date}'); return false;">
                                🗑 Удалить
                            </button>
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
        <div class="mt-3">
            <button class="btn btn-success" onclick="showCreateRaffleForm()">➕ Добавить розыгрыш</button>
        </div>
    `;
    
    // Обработчики для дат розыгрышей (используем делегирование событий)
    const raffleListEl = document.getElementById('raffle-list');
    if (raffleListEl) {
        raffleListEl.addEventListener('click', async (e) => {
            const link = e.target.closest('.raffle-date-link');
            if (link) {
                e.preventDefault();
                e.stopPropagation();
                const raffleDate = link.dataset.raffleDate;
                await showRaffleDetails(raffleDate);
            }
        });
    }

    const searchEl = document.getElementById('raffleSearch');
    if (searchEl) {
        searchEl.addEventListener('input', () => {
            const q = (searchEl.value || '').trim().toLowerCase();
            const items = document.querySelectorAll('[data-raffle-item="1"]');
            items.forEach(it => {
                const d = (it.getAttribute('data-raffle-date') || '').toLowerCase();
                const t = (it.getAttribute('data-raffle-title') || '').toLowerCase();
                const ok = !q || d.includes(q) || t.includes(q);
                it.style.display = ok ? '' : 'none';
            });
        });
    }
}

async function showRaffleDetails(raffleDate) {
    try {
        const [meta, stats, unchecked, questions] = await Promise.all([
            apiFetch(`/raffle/${raffleDate}/meta`),
            apiFetch(`/raffle/${raffleDate}/stats`),
            apiFetch(`/raffle/${raffleDate}/unchecked`),
            apiFetch(`/raffle/${raffleDate}/questions`)
        ]);
        
        const content = document.getElementById('content');
        const title = meta.title ? ` — ${escapeHtml(meta.title)}` : '';
        const startsAt = meta.starts_at_msk ? `<p class="text-muted mb-1">🕒 Начало: <strong>${escapeHtml(meta.starts_at_msk)}</strong> МСК</p>` : '';
        
        let uncheckedHtml = '';
        if (unchecked.unchecked.length > 0) {
            uncheckedHtml = `
                <h5 class="mt-4">Непроверенные ответы (${unchecked.total})</h5>
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Вопрос</th>
                                <th>Ответ</th>
                                <th>Действия</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${unchecked.unchecked.map(u => `
                                <tr>
                                    <td>${u.user_id}</td>
                                    <td>${u.question_text ? u.question_text.substring(0, 50) + '...' : '-'}</td>
                                    <td>${u.answer}</td>
                                    <td>
                                        <button class="btn btn-sm btn-success" onclick="approveAnswer('${raffleDate}', ${u.user_id})">✅</button>
                                        <button class="btn btn-sm btn-danger" onclick="denyAnswer('${raffleDate}', ${u.user_id})">❌</button>
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            `;
        }
        
        const questionsHtml = questions.questions ? questions.questions.map((q, idx) => {
            const questionId = q.id || (idx + 1);
            const questionTitle = q.title || 'Без названия';
            const questionText = q.text || q.question_text || 'Нет текста';
            return `
                <div class="card mb-2">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-start">
                            <div class="flex-grow-1">
                                <h6>Вопрос #${questionId}: ${escapeHtml(questionTitle)}</h6>
                                <p><strong>${escapeHtml(questionText)}</strong></p>
                            </div>
                            <div>
                                <button class="btn btn-sm btn-danger" onclick="removeRaffleQuestion('${raffleDate}', ${questionId})">🗑 Удалить</button>
                            </div>
                        </div>
                        <button class="btn btn-sm btn-primary mt-2" onclick="editRaffleQuestion('${raffleDate}', ${questionId})">✏️ Редактировать</button>
                    </div>
                </div>
            `;
        }).join('') : '<p>Вопросы не найдены</p>';
        
        content.innerHTML = `
            <h2>🎁 Розыгрыш ${raffleDate}${title}</h2>
            <button class="btn btn-secondary mb-3" onclick="loadRaffle()">◀️ Назад к списку</button>
            <div class="btn-group mb-3" role="group">
                <button class="btn btn-outline-primary" onclick="editRaffleMeta('${raffleDate}')">✏️ Мета</button>
                <button class="btn btn-outline-secondary" onclick="duplicateRaffle('${raffleDate}')">📋 Дублировать</button>
                <button class="btn btn-outline-info" onclick="previewRaffle('${raffleDate}')">👀 Превью</button>
                <button class="btn btn-outline-dark" onclick="rescheduleRaffleJobs('${raffleDate}')">🔁 Перепланировать</button>
            </div>
            
            <div class="card mb-3">
                <div class="card-body">
                    <h5>Статистика</h5>
                    ${startsAt}
                    <p>Всего участников: ${stats.total_participants || 0}</p>
                    <p>Принято: ${stats.approved || 0}</p>
                    <p>Отклонено: ${stats.denied || 0}</p>
                    <p>Не проверено: ${stats.unchecked || 0}</p>
                </div>
            </div>
            
            <div class="d-flex justify-content-between align-items-center mb-2">
                <h5>Вопросы</h5>
                <button class="btn btn-outline-primary btn-sm" onclick="showAddRaffleQuestionForm('${raffleDate}')">➕ Добавить вопрос</button>
            </div>
            ${questionsHtml}
            
            ${uncheckedHtml}
        `;
    } catch (error) {
        const content = document.getElementById('content');
        content.innerHTML = `
            <h2>🎁 Розыгрыш ${raffleDate}</h2>
            <button class="btn btn-secondary mb-3" onclick="loadRaffle()">◀️ Назад к списку</button>
            <div class="alert alert-danger">
                Ошибка при загрузке данных: ${error.message}
            </div>
        `;
    }
}

async function editRaffleQuestion(raffleDate, questionId) {
    try {
        const question = await apiFetch(`/raffle/${raffleDate}/questions/${questionId}`);
        
        const modalHtml = `
            <div class="modal fade" id="editRaffleQuestionModal" tabindex="-1">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">✏️ Редактирование вопроса #${questionId}</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <form id="editRaffleQuestionForm">
                                <div class="mb-3">
                                    <label class="form-label">Название вопроса</label>
                                    <input type="text" class="form-control" id="rqTitle" value="${escapeHtml(question.title || '')}" required>
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">Текст вопроса</label>
                                    <textarea class="form-control" id="rqText" rows="3" required>${escapeHtml(question.text || '')}</textarea>
                                </div>
                            </form>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Отмена</button>
                            <button type="button" class="btn btn-primary" onclick="saveRaffleQuestion('${raffleDate}', ${questionId})">💾 Сохранить</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        const existing = document.getElementById('editRaffleQuestionModal');
        if (existing) existing.remove();
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        const bsModal = new bootstrap.Modal(document.getElementById('editRaffleQuestionModal'));
        bsModal.show();
        document.getElementById('editRaffleQuestionModal').addEventListener('hidden.bs.modal', function() {
            this.remove();
        });
    } catch (e) {
        toastError(e.message || 'Не удалось загрузить вопрос');
    }
}

async function saveRaffleQuestion(raffleDate, questionId) {
    const form = document.getElementById('editRaffleQuestionForm');
    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }
    const title = document.getElementById('rqTitle').value.trim();
    const text = document.getElementById('rqText').value.trim();
    try {
        await apiAction(`/raffle/${raffleDate}/questions/${questionId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, text })
        });
        const modal = bootstrap.Modal.getInstance(document.getElementById('editRaffleQuestionModal'));
        if (modal) modal.hide();
        await showRaffleDetails(raffleDate);
    } catch (e) {
        // toast already
    }
}

async function toggleRaffleDate(raffleDate) {
    try {
        const result = await apiAction(`/raffle/${raffleDate}/toggle`, { method: 'POST' });
        toastSuccess(result.message || 'Сохранено');
        loadRaffle();
    } catch (error) {
        // toast already
    }
}

async function rescheduleRaffleJobs(raffleDate) {
    try {
        const resp = await apiAction(`/scheduler/raffle/${raffleDate}/reschedule`, { method: 'POST' });
        toastSuccess(resp.rescheduled ? 'Задачи пересозданы' : 'Scheduler не запущен');
    } catch (e) {
        // toast already
    }
}

async function editRaffleMeta(raffleDate) {
    try {
        const meta = await apiFetch(`/raffle/${raffleDate}/meta`);
        const currentTitle = meta.title || '';
        const currentStartsAtLocal = isoToDatetimeLocalMsk(meta.starts_at);

        const modalHtml = `
            <div class="modal fade" id="editRaffleMetaModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">✏️ Мета розыгрыша ${escapeHtml(raffleDate)}</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <form id="editRaffleMetaForm">
                                <div class="mb-3">
                                    <label class="form-label">Дата и время старта (МСК)</label>
                                    <input type="datetime-local" class="form-control" id="ermStartsAt" value="${escapeHtml(currentStartsAtLocal)}" required>
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">Заголовок</label>
                                    <input type="text" class="form-control" id="ermTitle" value="${escapeHtml(currentTitle)}" required>
                                </div>
                            </form>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Отмена</button>
                            <button type="button" class="btn btn-primary" onclick="saveRaffleMeta('${raffleDate}')">💾 Сохранить</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const existing = document.getElementById('editRaffleMetaModal');
        if (existing) existing.remove();
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        const bsModal = new bootstrap.Modal(document.getElementById('editRaffleMetaModal'));
        bsModal.show();
        document.getElementById('editRaffleMetaModal').addEventListener('hidden.bs.modal', function() {
            this.remove();
        });
    } catch (e) {
        toastError(e.message || 'Не удалось загрузить метаданные');
    }
}

async function saveRaffleMeta(raffleDate) {
    const form = document.getElementById('editRaffleMetaForm');
    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }
    const startsAt = document.getElementById('ermStartsAt').value;
    const title = document.getElementById('ermTitle').value.trim();
    try {
        const resp = await apiAction(`/raffle/${raffleDate}/meta`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ starts_at_local: startsAt, title })
        });
        toastSuccess(resp.scheduled ? 'Мета обновлена, задачи пересозданы' : 'Мета обновлена (scheduler не запущен)');
        const modal = bootstrap.Modal.getInstance(document.getElementById('editRaffleMetaModal'));
        if (modal) modal.hide();
        await showRaffleDetails(raffleDate);
    } catch (e) {
        // toast already
    }
}

async function deleteRaffle(raffleDate) {
    if (!confirm(`Удалить розыгрыш ${raffleDate}? Это действие нельзя отменить.`)) {
        return;
    }
    try {
        await apiAction(`/raffle/${raffleDate}`, { method: 'DELETE' });
        toastSuccess('Розыгрыш удален');
        loadRaffle();
    } catch (e) {
        // toast already
    }
}

async function duplicateRaffle(raffleDate) {
    try {
        const meta = await apiFetch(`/raffle/${raffleDate}/meta`);
        const currentTitle = meta.title || '';
        const defaultTitle = currentTitle ? `${currentTitle} (копия)` : 'Розыгрыш (копия)';

        const modalHtml = `
            <div class="modal fade" id="duplicateRaffleModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">📋 Дублировать розыгрыш ${escapeHtml(raffleDate)}</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <form id="duplicateRaffleForm">
                                <div class="mb-3">
                                    <label class="form-label">Новая дата и время (МСК)</label>
                                    <input type="datetime-local" class="form-control" id="drStartsAt" required>
                                </div>
                                <div class="mb-3">
                                    <label class="form-label">Заголовок</label>
                                    <input type="text" class="form-control" id="drTitle" value="${escapeHtml(defaultTitle)}" required>
                                </div>
                            </form>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Отмена</button>
                            <button type="button" class="btn btn-primary" onclick="saveDuplicateRaffle('${raffleDate}')">💾 Создать копию</button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        const existing = document.getElementById('duplicateRaffleModal');
        if (existing) existing.remove();
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        const bsModal = new bootstrap.Modal(document.getElementById('duplicateRaffleModal'));
        bsModal.show();
        document.getElementById('duplicateRaffleModal').addEventListener('hidden.bs.modal', function() {
            this.remove();
        });
    } catch (e) {
        toastError(e.message || 'Не удалось открыть форму дублирования');
    }
}

async function saveDuplicateRaffle(sourceRaffleDate) {
    const form = document.getElementById('duplicateRaffleForm');
    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }
    const startsAt = document.getElementById('drStartsAt').value;
    const title = document.getElementById('drTitle').value.trim();
    try {
        const resp = await apiAction(`/raffle/duplicate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source_raffle_date: sourceRaffleDate, starts_at_local: startsAt, title })
        });
        toastSuccess(`Розыгрыш продублирован на дату ${resp.raffle_date}${resp.scheduled ? ' (задачи обновлены)' : ''}`);
        const modal = bootstrap.Modal.getInstance(document.getElementById('duplicateRaffleModal'));
        if (modal) modal.hide();
        await showRaffleDetails(resp.raffle_date);
    } catch (e) {
        // toast already
    }
}

async function previewRaffle(raffleDate) {
    try {
        const [meta, questions] = await Promise.all([
            apiFetch(`/raffle/${raffleDate}/meta`),
            apiFetch(`/raffle/${raffleDate}/questions`)
        ]);
        
        const title = meta.title || 'Без заголовка';
        const startsAt = meta.starts_at_msk ? `Начало: ${escapeHtml(meta.starts_at_msk)} МСК` : 'Дата не указана';
        
        let questionsHtml = '';
        if (questions.questions && questions.questions.length > 0) {
            questionsHtml = questions.questions.map((q, idx) => {
                const questionId = q.id || (idx + 1);
                const questionTitle = q.title || 'Без названия';
                const questionText = q.text || q.question_text || 'Нет текста';
                return `
                    <div class="card mb-2">
                        <div class="card-body">
                            <h6>Вопрос #${questionId}: ${escapeHtml(questionTitle)}</h6>
                            <p>${escapeHtml(questionText)}</p>
                        </div>
                    </div>
                `;
            }).join('');
        } else {
            questionsHtml = '<p class="text-muted">Вопросы не найдены</p>';
        }
        
        const modalHtml = `
            <div class="modal fade" id="previewRaffleModal" tabindex="-1">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">👀 Превью розыгрыша ${escapeHtml(raffleDate)}</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <h5>${escapeHtml(title)}</h5>
                            <p class="text-muted">${startsAt}</p>
                            <hr>
                            <h6>Вопросы:</h6>
                            ${questionsHtml}
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Закрыть</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        const existing = document.getElementById('previewRaffleModal');
        if (existing) existing.remove();
        document.body.insertAdjacentHTML('beforeend', modalHtml);
        const bsModal = new bootstrap.Modal(document.getElementById('previewRaffleModal'));
        bsModal.show();
        document.getElementById('previewRaffleModal').addEventListener('hidden.bs.modal', function() {
            this.remove();
        });
    } catch (e) {
        toastError(e.message || 'Не удалось построить превью');
    }
}

function showAddRaffleQuestionForm(raffleDate) {
    const modalHtml = `
        <div class="modal fade" id="addRaffleQuestionModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">➕ Добавить вопрос</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <form id="addRaffleQuestionForm">
                            <div class="mb-3">
                                <label class="form-label">ID вопроса</label>
                                <input type="number" class="form-control" id="arqId" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Название вопроса</label>
                                <input type="text" class="form-control" id="arqTitle" required>
                            </div>
                            <div class="mb-3">
                                <label class="form-label">Текст вопроса</label>
                                <textarea class="form-control" id="arqText" rows="3" required></textarea>
                            </div>
                        </form>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Отмена</button>
                        <button type="button" class="btn btn-primary" onclick="saveAddRaffleQuestion('${raffleDate}')">💾 Добавить</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    const existing = document.getElementById('addRaffleQuestionModal');
    if (existing) existing.remove();
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    const bsModal = new bootstrap.Modal(document.getElementById('addRaffleQuestionModal'));
    bsModal.show();
    document.getElementById('addRaffleQuestionModal').addEventListener('hidden.bs.modal', function() {
        this.remove();
    });
}

async function saveAddRaffleQuestion(raffleDate) {
    const form = document.getElementById('addRaffleQuestionForm');
    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }
    const questionId = parseInt(document.getElementById('arqId').value);
    const title = document.getElementById('arqTitle').value.trim();
    const text = document.getElementById('arqText').value.trim();
    try {
        await apiAction(`/raffle/${raffleDate}/questions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question_id: questionId, title, text })
        });
        const modal = bootstrap.Modal.getInstance(document.getElementById('addRaffleQuestionModal'));
        if (modal) modal.hide();
        await showRaffleDetails(raffleDate);
    } catch (e) {
        // toast already
    }
}

async function removeRaffleQuestion(raffleDate, questionId) {
    if (!confirm(`Удалить вопрос #${questionId}?`)) {
        return;
    }
    try {
        await apiAction(`/raffle/${raffleDate}/questions/${questionId}`, { method: 'DELETE' });
        toastSuccess('Вопрос удален');
        await showRaffleDetails(raffleDate);
    } catch (e) {
        // toast already
    }
}

function showCreateRaffleForm() {
    const content = document.getElementById('content');
    content.innerHTML = `
        <h2>➕ Добавить розыгрыш</h2>
        <button class="btn btn-secondary mb-3" onclick="loadRaffle()">◀️ Назад к списку</button>

        <div class="card">
            <div class="card-body">
                <form id="createRaffleForm">
                    <div class="mb-3">
                        <label class="form-label">Дата и время розыгрыша (МСК)</label>
                        <input type="datetime-local" class="form-control" id="crStartsAt" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Заголовок розыгрыша</label>
                        <input type="text" class="form-control" id="crTitle" required>
                    </div>

                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <h5 class="mb-0">Вопросы</h5>
                        <button type="button" class="btn btn-outline-primary btn-sm" onclick="addCreateRaffleQuestion()">➕ Добавить вопрос</button>
                    </div>

                    <div id="crQuestions"></div>

                    <div class="mt-3">
                        <button type="submit" class="btn btn-success">💾 Создать розыгрыш</button>
                    </div>
                </form>
            </div>
        </div>
    `;

    window._crCounter = 0;
    addCreateRaffleQuestion();

    const form = document.getElementById('createRaffleForm');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await submitCreateRaffle();
    });
}

function addCreateRaffleQuestion() {
    const container = document.getElementById('crQuestions');
    if (!container) return;
    const id = (++window._crCounter);
    const block = document.createElement('div');
    block.className = 'card mb-3';
    block.setAttribute('data-cr-id', String(id));
    block.innerHTML = `
        <div class="card-body">
            <div class="d-flex justify-content-between align-items-center">
                <h6 class="mb-2">Вопрос #${id}</h6>
                <button type="button" class="btn btn-outline-danger btn-sm" onclick="removeCreateRaffleQuestion(${id})">🗑 Удалить</button>
            </div>
            <div class="mb-2">
                <label class="form-label">ID вопроса</label>
                <input type="number" class="form-control" id="crQId_${id}" value="${id}" required>
            </div>
            <div class="mb-2">
                <label class="form-label">Название вопроса</label>
                <input type="text" class="form-control" id="crQTitle_${id}" required>
            </div>
            <div class="mb-2">
                <label class="form-label">Текст вопроса</label>
                <textarea class="form-control" id="crQText_${id}" rows="2" required></textarea>
            </div>
        </div>
    `;
    container.appendChild(block);
    _ensureCreateRaffleRemoveButtons();
}

function removeCreateRaffleQuestion(id) {
    const container = document.getElementById('crQuestions');
    if (!container) return;
    const blocks = container.querySelectorAll('[data-cr-id]');
    if (blocks.length <= 1) {
        alert('Должен быть минимум 1 вопрос');
        return;
    }
    const el = container.querySelector(`[data-cr-id="${id}"]`);
    if (el) el.remove();
    _ensureCreateRaffleRemoveButtons();
}

function _ensureCreateRaffleRemoveButtons() {
    const container = document.getElementById('crQuestions');
    if (!container) return;
    const blocks = container.querySelectorAll('[data-cr-id]');
    const disableRemove = blocks.length <= 1;
    blocks.forEach(b => {
        const btn = b.querySelector('button.btn-outline-danger');
        if (btn) btn.disabled = disableRemove;
    });
}

async function submitCreateRaffle() {
    const startsAt = document.getElementById('crStartsAt').value;
    const title = document.getElementById('crTitle').value.trim();
    if (!startsAt) {
        alert('Выберите дату и время розыгрыша');
        return;
    }
    if (!title) {
        alert('Введите заголовок розыгрыша');
        return;
    }

    const container = document.getElementById('crQuestions');
    const blocks = Array.from(container.querySelectorAll('[data-cr-id]'));
    if (blocks.length < 1) {
        alert('Добавьте минимум 1 вопрос');
        return;
    }

    const questions = blocks.map((b) => {
        const id = b.getAttribute('data-cr-id');
        const questionId = parseInt(document.getElementById(`crQId_${id}`).value);
        const questionTitle = document.getElementById(`crQTitle_${id}`).value.trim();
        const questionText = document.getElementById(`crQText_${id}`).value.trim();
        return { id: questionId, title: questionTitle, text: questionText };
    });

    for (let i = 0; i < questions.length; i++) {
        const q = questions[i];
        if (!q.title || !q.text) {
            toastError(`Вопрос #${i + 1}: заполните все поля`);
            return;
        }
    }

    try {
        const resp = await apiAction('/raffle/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                starts_at_local: startsAt,
                title,
                questions
            })
        });
        toastSuccess(`Розыгрыш создан на дату ${resp.raffle_date}${resp.scheduled ? ' (задачи обновлены)' : ''}`);
        await showRaffleDetails(resp.raffle_date);
    } catch (error) {
        // toast уже показан в apiAction
    }
}


// Функции для действий
async function approveAnswer(raffleDate, userId) {
    try {
        await apiFetch(`/raffle/${raffleDate}/approve/${userId}`, { method: 'POST' });
        alert('Ответ одобрен!');
        loadPage('dashboard');
    } catch (error) {
        alert('Ошибка: ' + error.message);
    }
}

async function denyAnswer(raffleDate, userId) {
    try {
        await apiFetch(`/raffle/${raffleDate}/deny/${userId}`, { method: 'POST' });
        alert('Ответ отклонен!');
        loadPage('dashboard');
    } catch (error) {
        alert('Ошибка: ' + error.message);
    }
}

// Улучшенная страница билетиков
async function loadTickets() {
    const [stats, duplicates] = await Promise.all([
        apiFetch('/tickets/stats'),
        apiFetch('/tickets/duplicates')
    ]);
    
    const content = document.getElementById('content');
    
    let duplicatesHtml = '';
    if (duplicates.duplicates.length > 0) {
        duplicatesHtml = `
            <div class="alert alert-warning mt-3">
                <h5>⚠️ Обнаружено дублей: ${duplicates.duplicates.length}</h5>
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th>Билет №</th>
                                <th>Пользователи</th>
                                <th>Источник</th>
                                <th>Действия</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${duplicates.duplicates.map(dup => `
                                <tr>
                                    <td>${dup.ticket_number}</td>
                                    <td>${dup.user_ids.join(', ')}</td>
                                    <td>${dup.source}</td>
                                    <td>
                                        <button class="btn btn-sm btn-info" onclick="checkTicketTime(${dup.ticket_number})">⏰ Время</button>
                                        ${dup.user_ids.map(uid => `
                                            <button class="btn btn-sm btn-danger" onclick="removeTicket(${uid}, ${dup.ticket_number})">🗑️ Удалить</button>
                                        `).join('')}
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }
    
    content.innerHTML = `
        <h2>🎟 Билетики</h2>
        
        <div class="row mt-4">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-body">
                        <h5>Общая статистика</h5>
                        <p>Всего: <strong>${stats.total}</strong></p>
                        <p>Из квизов: ${stats.from_quiz}</p>
                        <p>Из розыгрышей: ${stats.from_raffle}</p>
                        <p>Диапазон: №${stats.min || 'N/A'} - №${stats.max || 'N/A'}</p>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card">
                    <div class="card-body">
                        <h5>Дубли</h5>
                        <p>В квизах: ${stats.duplicates.in_quiz}</p>
                        <p>В розыгрышах: ${stats.duplicates.in_raffle}</p>
                        <p>Между таблицами: ${stats.duplicates.cross_table}</p>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="card mt-3">
            <div class="card-body">
                <h5>🔍 Поиск билетика</h5>
                <div class="input-group">
                    <input type="number" id="ticketSearch" class="form-control" placeholder="Номер билетика">
                    <button class="btn btn-primary" onclick="searchTicket()">Найти</button>
                </div>
            </div>
        </div>
        
        ${duplicatesHtml}
    `;
}

// Поиск билетика
async function searchTicket() {
    const ticketNumber = document.getElementById('ticketSearch').value;
    if (!ticketNumber) {
        alert('Введите номер билетика');
        return;
    }
    
    try {
        const data = await apiFetch(`/tickets/check_time/${ticketNumber}`);
        showTicketInfo(data);
    } catch (error) {
        alert('Ошибка: ' + error.message);
    }
}

// Показать информацию о билетике
function showTicketInfo(data) {
    const content = document.getElementById('content');
    const ticketsHtml = data.tickets.map((t, i) => {
        let userInfoHtml = '';
        if (t.user) {
            const u = t.user;
            if (u.registration_completed) {
                // Пользователь зарегистрирован
                userInfoHtml = `
                    <div class="card mt-2">
                        <div class="card-body">
                            <h6>Информация о пользователе (зарегистрирован)</h6>
                            <p><strong>ID:</strong> ${u.id}</p>
                            <p><strong>Username:</strong> ${u.username || '-'}</p>
                            <p><strong>Имя в ТГ:</strong> ${u.first_name || '-'}</p>
                            <p><strong>Статус сотрудника:</strong> ${u.registration_status_display || u.registration_status || '-'}</p>
                            <p><strong>Имя (из регистрации):</strong> ${u.registration_first_name || '-'}</p>
                            <p><strong>Фамилия (из регистрации):</strong> ${u.registration_last_name || '-'}</p>
                            <p><strong>Должность (из регистрации):</strong> ${u.registration_position || '-'}</p>
                            <p><strong>Дата регистрации:</strong> ${u.created_at ? new Date(u.created_at).toLocaleString('ru-RU') : '-'}</p>
                        </div>
                    </div>
                `;
            } else {
                // Пользователь не зарегистрирован
                userInfoHtml = `
                    <div class="card mt-2">
                        <div class="card-body">
                            <h6>Информация о пользователе (не зарегистрирован)</h6>
                            <p><strong>ID:</strong> ${u.id}</p>
                            <p><strong>Username:</strong> ${u.username || '-'}</p>
                            <p><strong>Имя в ТГ:</strong> ${u.first_name || '-'}</p>
                        </div>
                    </div>
                `;
            }
        } else {
            // Пользователь не найден в БД
            userInfoHtml = `
                <div class="card mt-2">
                    <div class="card-body">
                        <h6>Информация о пользователе</h6>
                        <p><strong>ID:</strong> ${t.user_id}</p>
                        <p class="text-muted">Пользователь не найден в базе данных</p>
                    </div>
                </div>
            `;
        }
        
        return `
            <tr>
                <td>${i + 1}</td>
                <td>${t.user_id}</td>
                <td>${t.source}</td>
                <td>${t.date}</td>
                <td>${t.time_display}</td>
                <td>${t.db_id}</td>
                <td>
                    <button class="btn btn-sm btn-danger" onclick="removeTicket(${t.user_id}, ${data.ticket_number})">🗑️ Удалить</button>
                </td>
            </tr>
            <tr>
                <td colspan="7">${userInfoHtml}</td>
            </tr>
        `;
    }).join('');
    
    const modal = `
        <div class="modal fade" id="ticketModal" tabindex="-1">
            <div class="modal-dialog modal-xl">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">🎟 Билетик №${data.ticket_number}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <table class="table">
                            <thead>
                                <tr>
                                    <th>#</th>
                                    <th>ID пользователя</th>
                                    <th>Источник</th>
                                    <th>Дата</th>
                                    <th>Время</th>
                                    <th>ID БД</th>
                                    <th>Действия</th>
                                </tr>
                            </thead>
                            <tbody>${ticketsHtml}</tbody>
                        </table>
                        ${data.first_user ? `<p><strong>🏆 Первым получил:</strong> ID ${data.first_user.user_id} (${data.first_user.source})</p>` : ''}
                        ${data.same_time ? '<p class="text-warning">⚠️ Внимание: Оба пользователя получили билетик в одно и то же время!</p>' : ''}
                    </div>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', modal);
    const bsModal = new bootstrap.Modal(document.getElementById('ticketModal'));
    bsModal.show();
    
    document.getElementById('ticketModal').addEventListener('hidden.bs.modal', function() {
        this.remove();
    });
}

// Проверить время билетика
async function checkTicketTime(ticketNumber) {
    try {
        const data = await apiFetch(`/tickets/check_time/${ticketNumber}`);
        showTicketInfo(data);
    } catch (error) {
        alert('Ошибка: ' + error.message);
    }
}

// Удалить билетик
async function removeTicket(userId, ticketNumber) {
    if (!confirm(`Удалить билетик №${ticketNumber} у пользователя ${userId}?`)) {
        return;
    }
    
    try {
        await apiFetch(`/tickets/${userId}/${ticketNumber}`, { method: 'DELETE' });
        alert('Билетик удален!');
        loadPage('tickets');
    } catch (error) {
        alert('Ошибка: ' + error.message);
    }
}

// Улучшенная страница пользователей
let currentUserPage = 0;
let currentUserLimit = 100;
let showingRegistered = false;

async function loadUsers(page = 0) {
    currentUserPage = page;
    const skip = page * currentUserLimit;
    
    const endpoint = showingRegistered ? `/users/registered?skip=${skip}&limit=${currentUserLimit}` : `/users/?skip=${skip}&limit=${currentUserLimit}`;
    const users = await apiFetch(endpoint);
    
    const content = document.getElementById('content');
    
    const totalPages = Math.ceil(users.total / currentUserLimit);
    const paginationHtml = totalPages > 1 ? `
        <nav aria-label="Пагинация">
            <ul class="pagination justify-content-center">
                <li class="page-item ${page === 0 ? 'disabled' : ''}">
                    <a class="page-link" href="#" onclick="loadUsers(${page - 1}); return false;">Предыдущая</a>
                </li>
                <li class="page-item active">
                    <span class="page-link">Страница ${page + 1} из ${totalPages}</span>
                </li>
                <li class="page-item ${page >= totalPages - 1 ? 'disabled' : ''}">
                    <a class="page-link" href="#" onclick="loadUsers(${page + 1}); return false;">Следующая</a>
                </li>
            </ul>
        </nav>
    ` : '';
    
    content.innerHTML = `
        <h2>👥 Пользователи</h2>
        <p>Всего: ${users.total} ${showingRegistered ? '(только авторизованные)' : ''}</p>
        
        <div class="btn-group mb-3" role="group">
            <button type="button" class="btn ${!showingRegistered ? 'btn-primary' : 'btn-outline-primary'}" onclick="showingRegistered=false; loadUsers(0);">
                Все пользователи
            </button>
            <button type="button" class="btn ${showingRegistered ? 'btn-primary' : 'btn-outline-primary'}" onclick="showingRegistered=true; loadUsers(0);">
                Авторизованные пользователи
            </button>
        </div>
        
        <div class="card mt-3">
            <div class="card-body">
                <h5>🔍 Поиск пользователя</h5>
                <div class="input-group">
                    <input type="number" id="userSearch" class="form-control" placeholder="ID пользователя">
                    <button class="btn btn-primary" onclick="searchUser()">Найти</button>
                </div>
            </div>
        </div>
        
        <div class="table-responsive mt-3">
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Username</th>
                        <th>Имя</th>
                        <th>Знак</th>
                        <th>Подписан</th>
                        ${!showingRegistered ? '<th>Зарегистрирован</th>' : ''}
                        <th>Действия</th>
                    </tr>
                </thead>
                <tbody>
                    ${users.users.map(user => `
                        <tr>
                            <td>${user.id}</td>
                            <td>${user.username || '-'}</td>
                            <td>${user.first_name || '-'}</td>
                            <td>${user.zodiac_name || user.zodiac || '-'}</td>
                            <td>${user.subscribed ? '✅' : '❌'}</td>
                            ${!showingRegistered ? `<td>${user.registration_completed ? '✅' : '❌'}</td>` : ''}
                            <td>
                                <button class="btn btn-sm btn-info" onclick="viewUserTickets(${user.id})">🎟 Билетики</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
        ${paginationHtml}
    `;
}

// Поиск пользователя
async function searchUser() {
    const userId = document.getElementById('userSearch').value;
    if (!userId) {
        alert('Введите ID пользователя');
        return;
    }
    
    try {
        const user = await apiFetch(`/users/${userId}`);
        viewUserDetails(user);
    } catch (error) {
        alert('Ошибка: ' + error.message);
    }
}

// Показать детали пользователя
function viewUserDetails(user) {
    const modal = `
        <div class="modal fade" id="userModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">👤 Пользователь ${user.id}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <p><strong>Username:</strong> ${user.username || '-'}</p>
                        <p><strong>Имя:</strong> ${user.first_name || '-'}</p>
                        <p><strong>Знак зодиака:</strong> ${user.zodiac_name || user.zodiac || '-'}</p>
                        <p><strong>Подписан:</strong> ${user.subscribed ? '✅' : '❌'}</p>
                        <p><strong>Зарегистрирован:</strong> ${user.registration_completed ? '✅' : '❌'}</p>
                        <p><strong>Создан:</strong> ${user.created_at ? new Date(user.created_at).toLocaleString('ru-RU') : '-'}</p>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', modal);
    const bsModal = new bootstrap.Modal(document.getElementById('userModal'));
    bsModal.show();
    
    document.getElementById('userModal').addEventListener('hidden.bs.modal', function() {
        this.remove();
    });
}

// Показать билетики пользователя
async function viewUserTickets(userId) {
    try {
        const data = await apiFetch(`/tickets/user/${userId}`);
        const ticketsHtml = data.tickets.map(t => `
            <tr>
                <td>${t.ticket_number}</td>
                <td>${t.source}</td>
                <td>${t.date}</td>
                <td>${t.completed_at || t.timestamp ? new Date(t.completed_at || t.timestamp).toLocaleString('ru-RU') : '-'}</td>
                <td>
                    <button class="btn btn-sm btn-danger" onclick="removeTicket(${userId}, ${t.ticket_number})">🗑️ Удалить</button>
                </td>
            </tr>
        `).join('');
        
        const modal = `
            <div class="modal fade" id="userTicketsModal" tabindex="-1">
                <div class="modal-dialog modal-lg">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title">🎟 Билетики пользователя ${userId}</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <p>Всего билетиков: ${data.tickets.length}</p>
                            <div class="table-responsive">
                                <table class="table">
                                    <thead>
                                        <tr>
                                            <th>№</th>
                                            <th>Источник</th>
                                            <th>Дата</th>
                                            <th>Время</th>
                                            <th>Действия</th>
                                        </tr>
                                    </thead>
                                    <tbody>${ticketsHtml}</tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        document.body.insertAdjacentHTML('beforeend', modal);
        const bsModal = new bootstrap.Modal(document.getElementById('userTicketsModal'));
        bsModal.show();
        
        document.getElementById('userTicketsModal').addEventListener('hidden.bs.modal', function() {
            this.remove();
        });
    } catch (error) {
        alert('Ошибка: ' + error.message);
    }
}

// ----------------- Планировщик (операционка) -----------------
async function loadScheduler() {
    const [jobsData, quizList] = await Promise.all([
        apiFetch('/scheduler/jobs'),
        apiFetch('/quiz/list').catch(() => ({ quizzes: [] }))
    ]);

    const quizTitleByDate = new Map((quizList.quizzes || []).map(q => [q.quiz_date, q.title || null]));

    const content = document.getElementById('content');
    const running = !!jobsData.running;

    const jobs = jobsData.jobs || [];
    const rows = jobs.map(j => {
        const id = j.id || '';
        let kind = 'other';
        let quizDate = null;
        let action = null;

        if (id.startsWith('quiz_announcements_')) { kind = 'quiz'; quizDate = id.replace('quiz_announcements_', ''); action = 'announce'; }
        else if (id.startsWith('quiz_reminders_')) { kind = 'quiz'; quizDate = id.replace('quiz_reminders_', ''); action = 'remind'; }
        else if (id.startsWith('quiz_mark_')) { kind = 'quiz'; quizDate = id.replace('quiz_mark_', ''); action = 'mark'; }

        const title = quizDate ? (quizTitleByDate.get(quizDate) || '') : '';
        const nextRun = j.next_run_time ? isoToHumanMsk(j.next_run_time) : '-';

        const actionBtn = (kind === 'quiz' && quizDate && action) ? `
            <button class="btn btn-sm btn-outline-primary" onclick="runQuizAction('${quizDate}', '${action}')">▶️ Запустить</button>
        ` : '';

        const rescheduleBtn = (kind === 'quiz' && quizDate) ? `
            <button class="btn btn-sm btn-outline-dark" onclick="rescheduleQuizJobs('${quizDate}')">🔁 Перепланировать</button>
        ` : '';

        const openQuizBtn = (kind === 'quiz' && quizDate) ? `
            <button class="btn btn-sm btn-outline-secondary" onclick="showQuizDetails('${quizDate}')">🎯 Открыть</button>
        ` : '';

        return `
            <tr>
                <td><code>${escapeHtml(id)}</code></td>
                <td>${escapeHtml(kind)}</td>
                <td>${quizDate ? `<div><strong>${escapeHtml(quizDate)}</strong>${title ? ` — <span class="text-muted">${escapeHtml(title)}</span>` : ''}</div>` : '-'}</td>
                <td>${escapeHtml(nextRun)}</td>
                <td>
                    <div class="btn-group btn-group-sm" role="group">
                        ${openQuizBtn}
                        ${rescheduleBtn}
                        ${actionBtn}
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    content.innerHTML = `
        <h2>⏱ Планировщик</h2>
        <div class="card mb-3">
            <div class="card-body d-flex justify-content-between align-items-center">
                <div>
                    <div><strong>Статус:</strong> ${running ? '<span class="text-success">running</span>' : '<span class="text-danger">stopped</span>'}</div>
                    <div class="text-muted">Время в таблице: МСК (Europe/Moscow)</div>
                </div>
                <div>
                    <button class="btn btn-outline-primary" onclick="loadScheduler()">🔄 Обновить</button>
                </div>
            </div>
        </div>

        <div class="card">
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-sm align-middle">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Тип</th>
                                <th>Квиз</th>
                                <th>Следующий запуск (МСК)</th>
                                <th>Действия</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${rows || '<tr><td colspan="5" class="text-muted">Нет задач</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    `;
}

async function runQuizAction(quizDate, action) {
    try {
        await apiAction(`/scheduler/quiz/${quizDate}/run/${action}`, { method: 'POST' });
        toastSuccess(`Запущено: ${quizDate} / ${action}`);
    } catch (e) {
        // toast already
    }
}

// Улучшенная страница статистики
async function loadStats() {
    const [daily, weekly, health, errors] = await Promise.all([
        apiFetch('/stats/daily'),
        apiFetch('/stats/weekly'),
        apiFetch('/stats/health'),
        apiFetch('/stats/errors?limit=10')
    ]);
    
    const content = document.getElementById('content');
    
    const healthStatus = health.status === 'ok' ? 'success' : health.status === 'warning' ? 'warning' : 'danger';
    const healthIcon = health.status === 'ok' ? '✅' : health.status === 'warning' ? '⚠️' : '❌';
    
    content.innerHTML = `
        <h2>📈 Статистика</h2>
        
        <div class="row mt-4">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-body">
                        <h5>Ежедневный отчет</h5>
                        <p>Дата: ${daily.date}</p>
                        <p>Новых пользователей: ${daily.new_users}</p>
                        <p>Билетиков: ${daily.tickets.total}</p>
                        <p>Участников квизов: ${daily.activity.quiz_participants}</p>
                        <p>Участников розыгрышей: ${daily.activity.raffle_participants}</p>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card">
                    <div class="card-body">
                        <h5>Еженедельный отчет</h5>
                        <p>Период: ${weekly.period.from} - ${weekly.period.to}</p>
                        <p>Новых пользователей: ${weekly.new_users.total} (${weekly.new_users.avg_per_day.toFixed(1)}/день)</p>
                        <p>Билетиков: ${weekly.tickets.total} (${weekly.tickets.avg_per_day.toFixed(1)}/день)</p>
                        <p>Участников квизов: ${weekly.activity.quiz_participants}</p>
                        <p>Участников розыгрышей: ${weekly.activity.raffle_participants}</p>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="row mt-4">
            <div class="col-md-6">
                <div class="card border-${healthStatus}">
                    <div class="card-body">
                        <h5>${healthIcon} Здоровье системы</h5>
                        <p><strong>Статус:</strong> ${health.status}</p>
                        <p><strong>Scheduler:</strong> ${health.scheduler.status}</p>
                        <p><strong>База данных:</strong> ${health.database.status}</p>
                        <p><strong>Ошибок за час:</strong> ${health.errors.last_hour}</p>
                        <p><strong>Всего ошибок:</strong> ${health.errors.total}</p>
                        ${health.issues.length > 0 ? `
                            <div class="alert alert-warning mt-2">
                                <strong>Проблемы:</strong>
                                <ul class="mb-0">
                                    ${health.issues.map(issue => `<li>${issue}</li>`).join('')}
                                </ul>
                            </div>
                        ` : ''}
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card">
                    <div class="card-body">
                        <h5>⚠️ Последние ошибки</h5>
                        ${errors.errors.length > 0 ? `
                            <div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
                                <table class="table table-sm">
                                    <thead>
                                        <tr>
                                            <th>Время</th>
                                            <th>Сообщение</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${errors.errors.map(e => `
                                            <tr>
                                                <td>${new Date(e.time).toLocaleString('ru-RU')}</td>
                                                <td><small>${e.message.substring(0, 100)}${e.message.length > 100 ? '...' : ''}</small></td>
                                            </tr>
                                        `).join('')}
                                    </tbody>
                                </table>
                            </div>
                        ` : '<p>Ошибок не обнаружено ✅</p>'}
                    </div>
                </div>
            </div>
        </div>
    `;
}

// ==================== DICE (Кубик) ====================

async function loadDice() {
    const diceListData = await apiFetch('/dice/list');
    
    const content = document.getElementById('content');
    content.innerHTML = `
        <h2>🎲 Кубик</h2>
        <div class="card mb-3">
            <div class="card-body">
                <div class="input-group">
                    <span class="input-group-text">🔎</span>
                    <input type="text" class="form-control" id="diceSearch" placeholder="Поиск по ID или заголовку...">
                </div>
            </div>
        </div>
        <div class="list-group" id="dice-list">
            ${(diceListData.dice_events || []).map(item => {
                const diceId = item.dice_id;
                const title = item.title ? ` — <span class="text-muted">${escapeHtml(item.title)}</span>` : '';
                const startsAt = item.starts_at_msk ? `<small class="text-muted">(${escapeHtml(item.starts_at_msk)} МСК)</small>` : '';
                const isDisabled = !item.enabled;
                return `
                    <div class="list-group-item d-flex justify-content-between align-items-center" data-dice-item="1" data-dice-id="${escapeHtml(diceId)}" data-dice-title="${escapeHtml(item.title || '')}">
                        <a href="#" class="flex-grow-1 text-decoration-none dice-id-link" data-dice-id="${diceId}">
                            <div>
                                <strong>${diceId}</strong>${title}
                                ${isDisabled ? '<span class="badge bg-danger ms-2">Отключен</span>' : ''}
                            </div>
                            <div>${startsAt}</div>
                        </a>
                        <div>
                            <button class="btn btn-sm ${isDisabled ? 'btn-success' : 'btn-warning'}" onclick="event.stopPropagation(); toggleDice('${diceId}'); return false;">
                                ${isDisabled ? '✅ Включить' : '⏸️ Отключить'}
                            </button>
                            <button class="btn btn-sm btn-danger ms-1" onclick="event.stopPropagation(); deleteDice('${diceId}'); return false;">
                                🗑️ Удалить
                            </button>
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
        <div class="mt-3">
            <button class="btn btn-success" onclick="showCreateDiceForm()">➕ Добавить событие</button>
        </div>
    `;
    
    // Обработчики для событий dice
    const diceListEl = document.getElementById('dice-list');
    if (diceListEl) {
        diceListEl.addEventListener('click', async (e) => {
            const link = e.target.closest('.dice-id-link');
            if (link) {
                e.preventDefault();
                e.stopPropagation();
                const diceId = link.dataset.diceId;
                await showDiceDetails(diceId);
            }
        });
    }

    const searchEl = document.getElementById('diceSearch');
    if (searchEl) {
        searchEl.addEventListener('input', () => {
            const q = (searchEl.value || '').trim().toLowerCase();
            const items = document.querySelectorAll('[data-dice-item="1"]');
            items.forEach(it => {
                const d = (it.getAttribute('data-dice-id') || '').toLowerCase();
                const t = (it.getAttribute('data-dice-title') || '').toLowerCase();
                const ok = !q || d.includes(q) || t.includes(q);
                it.style.display = ok ? '' : 'none';
            });
        });
    }
}

async function showDiceDetails(diceId) {
    try {
        const diceData = await apiFetch(`/dice/${diceId}`);
        
        const content = document.getElementById('content');
        const title = diceData.title ? ` — ${escapeHtml(diceData.title)}` : '';
        const startsAt = diceData.starts_at_msk ? `<p class="text-muted mb-1">🕒 Начало: <strong>${escapeHtml(diceData.starts_at_msk)}</strong> МСК</p>` : '';
        const enabledBadge = diceData.enabled ? '<span class="badge bg-success">Включен</span>' : '<span class="badge bg-danger">Отключен</span>';
        
        content.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h2>🎲 ${escapeHtml(diceId)}${title}</h2>
                <div>
                    <button class="btn btn-secondary" onclick="loadDice()">← Назад</button>
                </div>
            </div>
            <div class="card">
                <div class="card-body">
                    <h5>Информация</h5>
                    <p><strong>ID:</strong> ${escapeHtml(diceId)}</p>
                    <p><strong>Заголовок:</strong> ${escapeHtml(diceData.title || '-')}</p>
                    ${startsAt}
                    <p><strong>Статус:</strong> ${enabledBadge}</p>
                    <div class="mt-3">
                        <button class="btn btn-primary" onclick="editDiceMeta('${diceId}')">✏️ Редактировать</button>
                        <button class="btn btn-warning ms-2" onclick="toggleDice('${diceId}')">
                            ${diceData.enabled ? '⏸️ Отключить' : '✅ Включить'}
                        </button>
                        <button class="btn btn-danger ms-2" onclick="deleteDice('${diceId}')">🗑️ Удалить</button>
                    </div>
                </div>
            </div>
        `;
    } catch (error) {
        toastError(error.message || 'Ошибка при загрузке деталей события');
    }
}

function showCreateDiceForm() {
    const content = document.getElementById('content');
    content.innerHTML = `
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h2>➕ Создать событие Dice</h2>
            <button class="btn btn-secondary" onclick="loadDice()">← Назад</button>
        </div>
        <div class="card">
            <div class="card-body">
                <form id="createDiceForm">
                    <div class="mb-3">
                        <label for="diceId" class="form-label">ID события *</label>
                        <input type="text" class="form-control" id="diceId" required placeholder="например: dice_2025_12_20">
                        <small class="form-text text-muted">Уникальный идентификатор события</small>
                    </div>
                    <div class="mb-3">
                        <label for="diceTitle" class="form-label">Заголовок *</label>
                        <input type="text" class="form-control" id="diceTitle" required placeholder="например: Проверка удачи">
                    </div>
                    <div class="mb-3">
                        <label for="diceStartsAt" class="form-label">Дата и время начала (МСК) *</label>
                        <input type="datetime-local" class="form-control" id="diceStartsAt" required>
                    </div>
                    <div class="mt-3">
                        <button type="submit" class="btn btn-success">✅ Создать</button>
                        <button type="button" class="btn btn-secondary" onclick="loadDice()">Отмена</button>
                    </div>
                </form>
            </div>
        </div>
    `;
    
    document.getElementById('createDiceForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const diceId = document.getElementById('diceId').value.trim();
        const title = document.getElementById('diceTitle').value.trim();
        const startsAt = document.getElementById('diceStartsAt').value;
        
        if (!diceId || !title || !startsAt) {
            toastError('Заполните все поля');
            return;
        }
        
        try {
            await apiAction('/dice/create', {
                method: 'POST',
                body: JSON.stringify({
                    dice_id: diceId,
                    title: title,
                    starts_at_local: startsAt
                })
            }, { successMessage: 'Событие создано' });
            await loadDice();
        } catch (error) {
            // Ошибка уже обработана в apiAction
        }
    });
}

async function editDiceMeta(diceId) {
    try {
        const diceData = await apiFetch(`/dice/${diceId}`);
        
        const content = document.getElementById('content');
        content.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h2>✏️ Редактировать событие</h2>
                <button class="btn btn-secondary" onclick="showDiceDetails('${diceId}')">← Назад</button>
            </div>
            <div class="card">
                <div class="card-body">
                    <form id="editDiceForm">
                        <div class="mb-3">
                            <label for="editDiceTitle" class="form-label">Заголовок *</label>
                            <input type="text" class="form-control" id="editDiceTitle" value="${escapeHtml(diceData.title || '')}" required>
                        </div>
                        <div class="mb-3">
                            <label for="editDiceStartsAt" class="form-label">Дата и время начала (МСК) *</label>
                            <input type="datetime-local" class="form-control" id="editDiceStartsAt" value="${diceData.starts_at_msk ? diceData.starts_at_msk.replace(' ', 'T') : ''}" required>
                        </div>
                        <div class="mt-3">
                            <button type="submit" class="btn btn-primary">💾 Сохранить</button>
                            <button type="button" class="btn btn-secondary" onclick="showDiceDetails('${diceId}')">Отмена</button>
                        </div>
                    </form>
                </div>
            </div>
        `;
        
        document.getElementById('editDiceForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const title = document.getElementById('editDiceTitle').value.trim();
            const startsAt = document.getElementById('editDiceStartsAt').value;
            
            if (!title || !startsAt) {
                toastError('Заполните все поля');
                return;
            }
            
            try {
                await apiAction(`/dice/${diceId}`, {
                    method: 'PUT',
                    body: JSON.stringify({
                        title: title,
                        starts_at_local: startsAt
                    })
                }, { successMessage: 'Событие обновлено' });
                await showDiceDetails(diceId);
            } catch (error) {
                // Ошибка уже обработана в apiAction
            }
        });
    } catch (error) {
        toastError(error.message || 'Ошибка при загрузке данных');
    }
}

async function toggleDice(diceId) {
    if (!confirm(`Вы уверены, что хотите ${document.querySelector(`[data-dice-id="${diceId}"]`)?.querySelector('.btn-warning, .btn-success')?.textContent.includes('Отключить') ? 'отключить' : 'включить'} это событие?`)) {
        return;
    }
    
    try {
        await apiAction(`/dice/${diceId}/toggle`, {
            method: 'POST'
        }, { successMessage: 'Статус изменен' });
        await loadDice();
    } catch (error) {
        // Ошибка уже обработана в apiAction
    }
}

async function deleteDice(diceId) {
    if (!confirm(`Вы уверены, что хотите удалить событие "${diceId}"? Это действие нельзя отменить.`)) {
        return;
    }
    
    try {
        await apiAction(`/dice/${diceId}`, {
            method: 'DELETE'
        }, { successMessage: 'Событие удалено' });
        await loadDice();
    } catch (error) {
        // Ошибка уже обработана в apiAction
    }
}

