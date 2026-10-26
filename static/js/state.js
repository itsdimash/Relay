import { defaultTeam } from './constants.js';

/** Mutable session state shared by features; server snapshots remain authoritative. */
export const state = {
  token: '',
  runs: [],
  selected: null,
  rendered: '',
  connected: false,
  loading: false,
  currentTeam: structuredClone(defaultTeam),
  imageDrafts: {
    task: [],
    followup: []
  },
  imageLoading: 0,
  pendingSource: null,
  buildError: null
};
