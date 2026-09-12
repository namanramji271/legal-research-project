/**
 * Browser-native Web Speech API utilities:
 * - SpeechRecognition for voice input (mic)
 * - SpeechSynthesis for voice output (read-aloud)
 */

export function isSpeechRecognitionSupported() {
  if (typeof window === "undefined") return false;
  return Boolean(window.SpeechRecognition || window.webkitSpeechRecognition);
}

export function createSpeechRecognition() {
  if (typeof window === "undefined") return null;
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) return null;
  const recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = "en-IN"; // Default to Indian English; falls back smoothly across browsers
  return recognition;
}

let currentUtterance = null;
let currentOnEndCallback = null;

export function isSpeechSynthesisSupported() {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function speakText(text, onStart, onEnd) {
  if (!isSpeechSynthesisSupported()) return;

  // Stop any active speech first (no overlapping audio)
  stopSpeaking();

  if (!text || !text.trim()) return;

  try {
    const utterance = new SpeechSynthesisUtterance(text);
    currentUtterance = utterance;
    currentOnEndCallback = onEnd;

    utterance.onstart = () => {
      if (onStart) onStart();
    };

    utterance.onend = () => {
      currentUtterance = null;
      currentOnEndCallback = null;
      if (onEnd) onEnd();
    };

    utterance.onerror = () => {
      currentUtterance = null;
      currentOnEndCallback = null;
      if (onEnd) onEnd();
    };

    window.speechSynthesis.speak(utterance);
  } catch (err) {
    console.error("Speech synthesis failed:", err);
    if (onEnd) onEnd();
  }
}

export function stopSpeaking() {
  if (!isSpeechSynthesisSupported()) return;
  try {
    window.speechSynthesis.cancel();
    if (currentOnEndCallback) {
      currentOnEndCallback();
    }
    currentUtterance = null;
    currentOnEndCallback = null;
  } catch {
    // Ignore cancel errors
  }
}
