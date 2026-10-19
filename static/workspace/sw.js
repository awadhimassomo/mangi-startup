const CACHE_NAME = 'fundos-pwa-v10';
const STATIC_ASSETS = [
    '/static/workspace/styles.css',
    '/static/workspace/manifest.json',
    '/static/workspace/icon-192.png',
    '/static/workspace/icon-512.png',
    '/static/workspace/apple-touch-icon.png',
    '/static/workspace/badge-72.png',
    '/quick-expense/',
];

// Install Event
self.addEventListener('install', function(event) {
    event.waitUntil(
        caches.open(CACHE_NAME).then(function(cache) {
            return cache.addAll(STATIC_ASSETS).catch(function(err) {
                console.warn('PWA: Failed to cache some static assets during install', err);
            });
        })
    );
    self.skipWaiting();
});

// Activate Event & Clean Old Caches
self.addEventListener('activate', function(event) {
    event.waitUntil(
        caches.keys().then(function(cacheNames) {
            return Promise.all(
                cacheNames.map(function(cache) {
                    if (cache !== CACHE_NAME) {
                        return caches.delete(cache);
                    }
                })
            );
        })
    );
    self.clients.claim();
});

// Fetch Event: Network-First for Navigation, Stale-While-Revalidate for Static
self.addEventListener('fetch', function(event) {
    const request = event.request;
    if (request.method !== 'GET') return;

    // Handle HTML navigation requests (pages)
    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request)
                .then(function(response) {
                    if (response.status === 200) {
                        const copy = response.clone();
                        caches.open(CACHE_NAME).then(function(cache) {
                            cache.put(request, copy);
                        });
                    }
                    return response;
                })
                .catch(function() {
                    return caches.match(request).then(function(cachedResponse) {
                        if (cachedResponse) return cachedResponse;
                        return caches.match('/quick-expense/');
                    });
                })
        );
        return;
    }

    // Handle Static Assets (CSS, JS, Fonts, Images)
    if (request.url.includes('/static/') || request.url.includes('fonts.googleapis') || request.url.includes('cdn.jsdelivr')) {
        event.respondWith(
            caches.match(request).then(function(cached) {
                const fetchPromise = fetch(request).then(function(networkResponse) {
                    if (networkResponse && networkResponse.status === 200) {
                        const copy = networkResponse.clone();
                        caches.open(CACHE_NAME).then(function(cache) {
                            cache.put(request, copy);
                        });
                    }
                    return networkResponse;
                }).catch(function() {
                    return cached;
                });
                return cached || fetchPromise;
            })
        );
        return;
    }

    // Default network with fallback
    event.respondWith(
        fetch(request).catch(function() {
            return caches.match(request);
        })
    );
});

// ── Web Push Notification Events ─────────────────────────────────────────────

self.addEventListener('push', function(event) {
    let data = {
        title: 'Mangi FundOS Notification',
        body: 'You have a new update in your workspace.',
        icon: '/static/workspace/icon-192.png',
        badge: '/static/workspace/badge-72.png',
        url: '/notifications/',
        tag: 'fundos-general'
    };

    if (event.data) {
        try {
            const parsed = event.data.json();
            data = Object.assign(data, parsed);
        } catch (e) {
            data.body = event.data.text();
        }
    }

    const options = {
        body: data.body,
        icon: data.icon || '/static/workspace/icon-192.png',
        badge: data.badge || '/static/workspace/badge-72.png',
        tag: data.tag || ('fundos-notif-' + Date.now()),
        data: {
            url: data.url || '/notifications/',
            timestamp: Date.now()
        },
        vibrate: [100, 50, 100],
        renotify: true,
        actions: [
            { action: 'open', title: 'Open Workspace' },
            { action: 'dismiss', title: 'Dismiss' }
        ]
    };

    event.waitUntil(
        self.registration.showNotification(data.title, options)
    );
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();

    if (event.action === 'dismiss') {
        return;
    }

    const targetUrl = (event.notification.data && event.notification.data.url) ? event.notification.data.url : '/notifications/';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clientList) {
            for (let i = 0; i < clientList.length; i++) {
                const client = clientList[i];
                if (client.url && 'focus' in client) {
                    client.navigate(targetUrl);
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});
