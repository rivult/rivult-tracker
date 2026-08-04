/** Build-time feature flags.
 *
 * These exist so a half-finished area can be hidden from users without
 * deleting working code — flip the flag, rebuild, and it's back.
 */

/** Cloud account / sync / billing UI (the Account page).
 *
 * FALSE in this build: the backend service behind it is not deployed, so every
 * one of those screens can only show a network error, and a page that always
 * errors reads as "this app is broken" — worse than the feature simply not
 * existing yet.
 *
 * The plumbing underneath is complete and tested; when the service goes live,
 * flip this to true. Keep in mind the separate
 * `PAYWALL_ENABLED` switches in `state/DataContext.tsx` and
 * `bedwars_parser/server.py` — those gate premium LOCKS, this gates the
 * account UI. Turning the paywall on while this is false would lock features
 * with no way to reach the upgrade screen.
 */
export const CLOUD_ENABLED = false;
