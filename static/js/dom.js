/** Shared DOM lookup and safe text interpolation. */
export const $ = id => document.getElementById(id);
// Read the current preference when an action happens, including changes made while Relay is open.
export const scrollBehavior = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
export const e = value => String(value ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
})[c]);
