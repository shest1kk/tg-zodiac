// Базовый JavaScript для админ-панели

const API_BASE = '/api';

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
            case 'stats':
                await loadStats();
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
        <div class="list-group" id="quiz-list">
            ${(quizListData.quizzes || []).map(item => {
                const date = item.quiz_date;
                const title = item.title ? ` — <span class="text-muted">${escapeHtml(item.title)}</span>` : '';
                const startsAt = item.starts_at_msk ? `<small class="text-muted">(${escapeHtml(item.starts_at_msk)} МСК)</small>` : '';
                const isDisabled = disabledSet.has(date);
                return `
                    <div class="list-group-item d-flex justify-content-between align-items-center">
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
                            <h6>Вопрос #${questionId}</h6>
                            <p><strong>${questionText}</strong></p>
                            ${optionsHtml}
                            <button class="btn btn-sm btn-primary mt-2" onclick="editQuizQuestion('${quizDate}', ${questionId})">✏️ Редактировать</button>
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        content.innerHTML = `
            <h2>🎯 Квиз ${quizDate}${title}</h2>
            <button class="btn btn-secondary mb-3" onclick="loadQuiz()">◀️ Назад к списку</button>
            
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
            
            <h5>Вопросы</h5>
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
            alert(`Вопрос #${i + 1}: пустой текст`);
            return;
        }
        for (const k of ["1","2","3","4"]) {
            if (!q.options[k]) {
                alert(`Вопрос #${i + 1}: вариант ${k} обязателен`);
                return;
            }
        }
        if (!["1","2","3","4"].includes(q.correct_answer)) {
            alert(`Вопрос #${i + 1}: выберите правильный ответ`);
            return;
        }
    }

    try {
        const resp = await apiFetch('/quiz/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                starts_at_local: startsAt,
                title,
                questions
            })
        });

        alert(`✅ Квиз создан на дату ${resp.quiz_date}${resp.scheduled ? ' (задачи в планировщике обновлены)' : ''}`);
        await loadQuiz();
    } catch (error) {
        alert('Ошибка: ' + error.message);
    }
}

async function toggleQuizDate(quizDate) {
    try {
        const result = await apiFetch(`/quiz/${quizDate}/toggle`, { method: 'POST' });
        alert(result.message);
        loadQuiz();
    } catch (error) {
        alert('Ошибка: ' + error.message);
    }
}

async function editQuizQuestion(quizDate, questionId) {
    try {
        // Получаем данные вопроса
        const questionsData = await apiFetch(`/quiz/${quizDate}/questions`);
        const question = questionsData.questions.find(q => q.id === questionId || q.id === parseInt(questionId));
        
        if (!question) {
            alert('Вопрос не найден');
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
        const response = await apiFetch(`/quiz/${quizDate}/questions/${questionId}`, {
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
            
            alert('✅ Вопрос успешно обновлен!');
        } else {
            alert('Ошибка: ' + (response.message || 'Не удалось сохранить вопрос'));
        }
    } catch (error) {
        alert('Ошибка при сохранении: ' + error.message);
    }
}

// Розыгрыши
async function loadRaffle() {
    const dates = await apiFetch('/raffle/dates');
    
    const content = document.getElementById('content');
    content.innerHTML = `
        <h2>🎁 Розыгрыши</h2>
        <div class="list-group">
            ${dates.dates.map(date => `
                <a href="#" class="list-group-item list-group-item-action" data-raffle-date="${date}">
                    ${date}
                </a>
            `).join('')}
        </div>
    `;
    
    // Обработчики для дат розыгрышей
    document.querySelectorAll('[data-raffle-date]').forEach(item => {
        item.addEventListener('click', async (e) => {
            e.preventDefault();
            const raffleDate = item.dataset.raffleDate;
            await showRaffleDetails(raffleDate);
        });
    });
}

async function showRaffleDetails(raffleDate) {
    const [stats, unchecked, questions] = await Promise.all([
        apiFetch(`/raffle/${raffleDate}/stats`),
        apiFetch(`/raffle/${raffleDate}/unchecked`),
        apiFetch(`/raffle/${raffleDate}/questions`)
    ]);
    
    const content = document.getElementById('content');
    
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
    
    const questionsHtml = questions.questions ? questions.questions.map((q, idx) => `
        <div class="card mb-2">
            <div class="card-body">
                <h6>Вопрос #${q.id || idx + 1}</h6>
                <p><strong>${q.question || q.question_text || 'Нет текста'}</strong></p>
                ${q.options ? `
                    <ul>
                        ${q.options.map((opt, i) => `
                            <li>${i + 1}. ${opt} ${i === (q.correct_answer || q.correct) ? '✅' : ''}</li>
                        `).join('')}
                    </ul>
                ` : ''}
                <button class="btn btn-sm btn-primary" onclick="editRaffleQuestion('${raffleDate}', ${q.id || idx + 1})">✏️ Редактировать</button>
            </div>
        </div>
    `).join('') : '<p>Вопросы не найдены</p>';
    
    content.innerHTML = `
        <h2>🎁 Розыгрыш ${raffleDate}</h2>
        <button class="btn btn-secondary mb-3" onclick="loadRaffle()">◀️ Назад к списку</button>
        
        <div class="card mb-3">
            <div class="card-body">
                <h5>Статистика</h5>
                <p>Всего участников: ${stats.total_participants}</p>
                <p>Принято: ${stats.approved}</p>
                <p>Отклонено: ${stats.denied}</p>
                <p>Не проверено: ${stats.unchecked}</p>
            </div>
        </div>
        
        <h5>Вопросы</h5>
        ${questionsHtml}
        
        ${uncheckedHtml}
    `;
}

async function editRaffleQuestion(raffleDate, questionId) {
    // TODO: Реализовать модальное окно для редактирования
    alert(`Редактирование вопроса ${questionId} розыгрыша ${raffleDate} (в разработке)`);
}


// Функции для действий
async function approveAnswer(raffleDate, userId) {
    try {
        await apiFetch(`/raffle/${raffleDate}/approve/${userId}`, { method: 'POST' });
        alert('Ответ одобрен!');
        loadPage('raffle');
    } catch (error) {
        alert('Ошибка: ' + error.message);
    }
}

async function denyAnswer(raffleDate, userId) {
    try {
        await apiFetch(`/raffle/${raffleDate}/deny/${userId}`, { method: 'POST' });
        alert('Ответ отклонен!');
        loadPage('raffle');
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
    const ticketsHtml = data.tickets.map((t, i) => `
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
    `).join('');
    
    const modal = `
        <div class="modal fade" id="ticketModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
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

