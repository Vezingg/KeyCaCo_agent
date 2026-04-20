/**
 * firebase-config.js
 * ──────────────────
 * Firebase Firestore configuration for persistent chat history.
 *
 * HOW TO SET UP:
 *  1. Go to https://console.firebase.google.com/
 *  2. Create a project (or use an existing one)
 *  3. Add a Web app inside the project
 *  4. Copy the firebaseConfig values below
 *  5. In Firestore Database, create a database (start in test mode for development)
 *
 * ⚠️  NOTE: Replace all "YOUR_..." placeholders with your actual values.
 *     Until you do, chat history will NOT persist (only in-memory for the session).
 */

import { initializeApp } from 'https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js';
import { getFirestore } from 'https://www.gstatic.com/firebasejs/10.12.0/firebase-firestore.js';

// ── Firebase project config ────────────────────────────────────────────────
const firebaseConfig = {
    apiKey: "AIzaSyAUxbro0WCsN-BuTMW1mltlcVf-P5D2hMU",
    authDomain: "ks-agent-493211-fcb85.firebaseapp.com",
    projectId: "ks-agent-493211-fcb85",
    storageBucket: "ks-agent-493211-fcb85.firebasestorage.app",
    messagingSenderId: "476895652625",
    appId: "1:476895652625:web:55a8706a92917be321fab0",
    measurementId: "G-7T7S81QY7L",
};
// ───────────────────────────────────────────────────────────────────────────

/**
 * Returns a Firestore instance if Firebase is properly configured,
 * or null if the placeholders have not been replaced yet.
 * The app gracefully degrades to in-memory history when null.
 */
function _initFirebase() {
    const isConfigured = Object.values(firebaseConfig).every(
        (v) => !String(v).startsWith("YOUR_")
    );

    if (!isConfigured) {
        console.warn(
            "[College Agent] Firebase not configured — chat history will only persist " +
            "for the current session. Edit /static/firebase-config.js to enable permanent storage."
        );
        return null;
    }

    try {
        const firebaseApp = initializeApp(firebaseConfig);
        const db = getFirestore(firebaseApp);
        console.info("[College Agent] ✅ Firebase connected — chat history is permanent.");
        return db;
    } catch (err) {
        console.error("[College Agent] Firebase init error:", err.message);
        return null;
    }
}

export const db = _initFirebase();
