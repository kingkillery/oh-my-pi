/**
 * Maps between Gemini Interactions API Computer Use actions and the internal
 * canonical ComputerUseAction representation used by the agent.proto schema.
 *
 * Gemini uses normalized 0-999 coordinates; the internal proto uses actual
 * pixel coordinates. Callers must denormalize before passing to this mapper.
 *
 * @see google-interactions-types.ts for the wire action names
 * @see cursor/proto/agent.proto for the internal ComputerUseAction message
 */

import type { FunctionCallStep } from "./google-interactions-types";

// ---------------------------------------------------------------------------
// Internal action types (mirrors agent.proto ComputerUseAction subtypes)
// ---------------------------------------------------------------------------

export interface Coordinate {
	x: number;
	y: number;
}

export interface InternalMouseMove {
	type: "mouse_move";
	coordinate: Coordinate;
}

export interface InternalClick {
	type: "click";
	coordinate?: Coordinate;
	button: number;
	count: number;
}

export interface InternalMouseDown {
	type: "mouse_down";
	coordinate?: Coordinate;
}

export interface InternalMouseUp {
	type: "mouse_up";
	coordinate?: Coordinate;
}

export interface InternalDrag {
	type: "drag";
	path: Coordinate[];
	button: number;
}

export interface InternalScroll {
	type: "scroll";
	coordinate?: Coordinate;
	direction: number;
	amount: number;
}

export interface InternalType {
	type: "type";
	text: string;
}

export interface InternalKey {
	type: "key";
	key: string;
	holdDurationMs?: number;
}

export interface InternalWait {
	type: "wait";
	durationMs: number;
}

export interface InternalScreenshot {
	type: "screenshot";
}

export interface InternalNavigate {
	type: "navigate";
	url: string;
}

export interface InternalGoBack {
	type: "go_back";
}

export interface InternalGoForward {
	type: "go_forward";
}

export type InternalAction =
	| InternalMouseMove
	| InternalClick
	| InternalMouseDown
	| InternalMouseUp
	| InternalDrag
	| InternalScroll
	| InternalType
	| InternalKey
	| InternalWait
	| InternalScreenshot
	| InternalNavigate
	| InternalGoBack
	| InternalGoForward;

// ---------------------------------------------------------------------------
// Coordinate denormalization
// ---------------------------------------------------------------------------

const NORMALIZED_MAX = 1000;

export function denormalizeCoordinate(x: number, y: number, screenWidth: number, screenHeight: number): Coordinate {
	return {
		x: Math.floor((x / NORMALIZED_MAX) * screenWidth),
		y: Math.floor((y / NORMALIZED_MAX) * screenHeight),
	};
}

// ---------------------------------------------------------------------------
// Mapper: Interactions API function_call -> InternalAction
// ---------------------------------------------------------------------------

const SCROLL_DIRECTION_MAP: Record<string, number> = {
	up: 0,
	down: 1,
	left: 2,
	right: 3,
};

const CLICK_COUNT_MAP: Record<string, number> = {
	click: 1,
	double_click: 2,
	triple_click: 3,
};

const BUTTON_MAP: Record<string, number> = {
	click: 0,
	double_click: 0,
	triple_click: 0,
	middle_click: 1,
	right_click: 2,
};

export function mapInteractionsAction(
	step: FunctionCallStep,
	screenWidth: number,
	screenHeight: number,
): InternalAction {
	const args = step.arguments;
	const x = args.x as number | undefined;
	const y = args.y as number | undefined;
	const coord =
		x !== undefined && y !== undefined ? denormalizeCoordinate(x, y, screenWidth, screenHeight) : undefined;

	switch (step.name) {
		case "click":
		case "double_click":
		case "triple_click":
		case "middle_click":
		case "right_click":
			return {
				type: "click",
				coordinate: coord,
				button: BUTTON_MAP[step.name] ?? 0,
				count: CLICK_COUNT_MAP[step.name] ?? 1,
			};

		case "mouse_down":
			return { type: "mouse_down", coordinate: coord };

		case "mouse_up":
			return { type: "mouse_up", coordinate: coord };

		case "move":
			return { type: "mouse_move", coordinate: coord! };

		case "type": {
			const text = args.text as string;
			const pressEnter = args.press_enter as boolean | undefined;
			return {
				type: "type",
				text: pressEnter ? `${text}\n` : text,
			};
		}

		case "drag_and_drop": {
			const startX = args.start_x as number;
			const startY = args.start_y as number;
			const endX = args.end_x as number;
			const endY = args.end_y as number;
			return {
				type: "drag",
				path: [
					denormalizeCoordinate(startX, startY, screenWidth, screenHeight),
					denormalizeCoordinate(endX, endY, screenWidth, screenHeight),
				],
				button: 0,
			};
		}

		case "scroll":
			return {
				type: "scroll",
				coordinate: coord,
				direction: SCROLL_DIRECTION_MAP[args.direction as string] ?? 1,
				amount: Math.floor(((args.magnitude_in_pixels as number | undefined) ?? 300) / 100),
			};

		case "press_key":
		case "key_down":
		case "key_up":
			return { type: "key", key: args.key as string };

		case "hotkey":
			return { type: "key", key: (args.keys as string[]).join("+") };

		case "wait":
			return { type: "wait", durationMs: ((args.seconds as number | undefined) ?? 1) * 1000 };

		case "take_screenshot":
			return { type: "screenshot" };

		case "navigate":
			return { type: "navigate", url: args.url as string };

		case "go_back":
			return { type: "go_back" };

		case "go_forward":
			return { type: "go_forward" };

		case "long_press":
			return {
				type: "click",
				coordinate: coord,
				button: 0,
				count: 1,
			};

		case "open_app":
		case "list_apps":
			return { type: "key", key: "" };

		default:
			return { type: "wait", durationMs: 0 };
	}
}
