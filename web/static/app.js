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
    const [systemStats, dailyReport] = await Promise.all([
        apiFetch('/stats/system'),
        apiFetch('/stats/daily')
    ]);
    
    const content = document.getElementById('content');
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
    `;
}

// Билетики
async function loadTickets() {
    const [stats, duplicates] = await Promise.all([
        apiFetch('/tickets/stats'),
        apiFetch('/tickets/duplicates')
    ]);
    
    const content = document.getElementById('content');
    let duplicatesHtml = '';
    
    if (duplicates.duplicates.length > 0) {
        duplicatesHtml = `
            <div class="alert alert-warning">
                <h5>⚠️ Обнаружено дублей: ${duplicates.duplicates.length}</h5>
                <ul>
                    ${duplicates.duplicates.map(dup => 
                        `<li>Билет №${dup.ticket_number} - пользователи: ${dup.user_ids.join(', ')} (${dup.source})</li>`
                    ).join('')}
                </ul>
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
                        <p>Диапазон: №${stats.min} - №${stats.max}</p>
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
        
        ${duplicatesHtml}
    `;
}

// Пользователи
async function loadUsers() {
    const users = await apiFetch('/users/?limit=50');
    
    const content = document.getElementById('content');
    content.innerHTML = `
        <h2>👥 Пользователи</h2>
        <p>Всего: ${users.total}</p>
        
        <div class="table-responsive">
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Username</th>
                        <th>Имя</th>
                        <th>Знак</th>
                        <th>Подписан</th>
                        <th>Зарегистрирован</th>
                    </tr>
                </thead>
                <tbody>
                    ${users.users.map(user => `
                        <tr>
                            <td>${user.id}</td>
                            <td>${user.username || '-'}</td>
                            <td>${user.first_name || '-'}</td>
                            <td>${user.zodiac || '-'}</td>
                            <td>${user.subscribed ? '✅' : '❌'}</td>
                            <td>${user.registration_completed ? '✅' : '❌'}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

// Квизы
async function loadQuiz() {
    const dates = await apiFetch('/quiz/dates');
    
    const content = document.getElementById('content');
    content.innerHTML = `
        <h2>🎯 Квизы</h2>
        <div class="list-group">
            ${dates.dates.map(date => `
                <a href="#" class="list-group-item list-group-item-action" data-quiz-date="${date}">
                    ${date}
                </a>
            `).join('')}
        </div>
    `;
    
    // Обработчики для дат квизов
    document.querySelectorAll('[data-quiz-date]').forEach(item => {
        item.addEventListener('click', async (e) => {
            e.preventDefault();
            const quizDate = item.dataset.quizDate;
            const stats = await apiFetch(`/quiz/${quizDate}/stats`);
            
            content.innerHTML = `
                <h2>🎯 Квиз ${quizDate}</h2>
                <div class="card">
                    <div class="card-body">
                        <h5>Статистика</h5>
                        <p>Всего участников: ${stats.total_participants}</p>
                        <p>Получили билетик: ${stats.with_tickets}</p>
                        <p>Не получили билетик: ${stats.no_tickets}</p>
                        <p>Не приняли участие: ${stats.non_participants}</p>
                    </div>
                </div>
            `;
        });
    });
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
            const [stats, unchecked] = await Promise.all([
                apiFetch(`/raffle/${raffleDate}/stats`),
                apiFetch(`/raffle/${raffleDate}/unchecked`)
            ]);
            
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
                                        <td>${u.question_text.substring(0, 50)}...</td>
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
            
            content.innerHTML = `
                <h2>🎁 Розыгрыш ${raffleDate}</h2>
                <div class="card">
                    <div class="card-body">
                        <h5>Статистика</h5>
                        <p>Всего участников: ${stats.total_participants}</p>
                        <p>Принято: ${stats.approved}</p>
                        <p>Отклонено: ${stats.denied}</p>
                        <p>Не проверено: ${stats.unchecked}</p>
                    </div>
                </div>
                ${uncheckedHtml}
            `;
        });
    });
}

// Статистика
async function loadStats() {
    const [daily, weekly] = await Promise.all([
        apiFetch('/stats/daily'),
        apiFetch('/stats/weekly')
    ]);
    
    const content = document.getElementById('content');
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
    `;
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

