/**
 * Stops a session that keeps making the same tool call (product-upgrade-guardrails).
 *
 * A small model can fall into repeating one call whose output never changes: run 78's matrix
 * session ran the same `bash` command 304 times in a row until the product timeout. Every
 * repeat makes the context more periodic and the next repeat more likely, so nothing inside the
 * session breaks the cycle. This extension counts consecutive calls with the same tool and
 * arguments. Past ALLOWED it refuses the call and tells the model why, which is often enough to
 * get it moving; at STOP it refuses and ends the session, and the runner then treats it like any
 * session that ended without an acceptable result.
 *
 * Only consecutive repeats count: a call that is repeated after other work in between is
 * ordinary, and one with different arguments resets the count.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const ALLOWED = 2;
const STOP = 5;

/** The call's identity: its tool and its arguments with object keys sorted, so that the same
 * arguments in another order still count as the same call. */
function signature(toolName: string, input: unknown): string {
	const canonical = (value: unknown): unknown => {
		if (Array.isArray(value)) return value.map(canonical);
		if (value && typeof value === "object") {
			return Object.fromEntries(
				Object.keys(value as object)
					.sort()
					.map((key) => [key, canonical((value as Record<string, unknown>)[key])]),
			);
		}
		return value;
	};
	return JSON.stringify([toolName, canonical(input)]);
}

export default function (pi: ExtensionAPI) {
	let last = "";
	let count = 0;

	pi.on("tool_call", async (event) => {
		const current = signature(event.toolName, event.input);
		count = current === last ? count + 1 : 1;
		last = current;
		if (count <= ALLOWED) return undefined;
		if (count >= STOP) {
			console.error(`loop-guard: stopped the session after ${count} identical ${event.toolName} calls in a row`);
			return {
				block: true,
				terminate: true,
				reason: `Stopped: this is the same ${event.toolName} call ${count} times in a row. The session is ending.`,
			};
		}
		return {
			block: true,
			reason:
				`Not run: this is the same ${event.toolName} call ${count} times in a row, and its output is ` +
				"already above. Repeating it will not tell you anything new. Look back at what the earlier " +
				"results showed, work out which step of the procedure you have already finished, and continue " +
				`with the next one. The session ends if you make this call ${STOP} times in a row.`,
		};
	});
}
