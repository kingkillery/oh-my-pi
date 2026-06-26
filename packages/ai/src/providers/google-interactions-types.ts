/**
 * Wire types for the Google Gemini Interactions API.
 *
 * The Interactions API is a distinct surface from `generateContent` / Vertex AI.
 * It powers agentic workflows with built-in tools like Computer Use, Google
 * Search, Code Execution, and others.
 *
 * Endpoint: POST https://generativelanguage.googleapis.com/v1beta/interactions
 *
 * @see https://ai.google.dev/gemini-api/docs/computer-use
 * @see https://ai.google.dev/gemini-api/docs/interactions-overview
 */

// ---------------------------------------------------------------------------
// Computer Use environments
// ---------------------------------------------------------------------------

export type ComputerUseEnvironment = "browser" | "mobile" | "desktop";

// ---------------------------------------------------------------------------
// Tool declarations
// ---------------------------------------------------------------------------

export interface ComputerUseTool {
	type: "computer_use";
	environment: ComputerUseEnvironment;
	enable_prompt_injection_detection?: boolean;
	excluded_predefined_functions?: string[];
}

export interface GoogleSearchTool {
	type: "google_search";
}

export interface CodeExecutionTool {
	type: "code_execution";
}

export interface UrlContextTool {
	type: "url_context";
}

export type InteractionsTool = ComputerUseTool | GoogleSearchTool | CodeExecutionTool | UrlContextTool;

// ---------------------------------------------------------------------------
// Input types
// ---------------------------------------------------------------------------

export interface TextInputPart {
	type: "text";
	text: string;
}

export interface ImageInputPart {
	type: "image";
	data: string;
	mime_type: string;
}

export type InputPart = TextInputPart | ImageInputPart;
export type InteractionsInput = string | InputPart[];

// ---------------------------------------------------------------------------
// Function result (sent back as user turn for multi-step agent loops)
// ---------------------------------------------------------------------------

export interface FunctionResultPart {
	type: "function_result";
	name: string;
	call_id: string;
	result: InputPart[];
}

// ---------------------------------------------------------------------------
// Request
// ---------------------------------------------------------------------------

export interface InteractionsRequest {
	model: string;
	input: InteractionsInput | FunctionResultPart[];
	tools?: InteractionsTool[];
	previous_interaction_id?: string;
}

// ---------------------------------------------------------------------------
// Response steps
// ---------------------------------------------------------------------------

export interface FunctionCallStep {
	type: "function_call";
	id: string;
	name: string;
	arguments: Record<string, unknown>;
}

export interface ModelOutputContentBlock {
	type: "text";
	text: string;
}

export interface ModelOutputStep {
	type: "model_output";
	content: ModelOutputContentBlock[];
}

export type InteractionStep = FunctionCallStep | ModelOutputStep;

// ---------------------------------------------------------------------------
// Response
// ---------------------------------------------------------------------------

export interface InteractionsResponse {
	id: string;
	steps: InteractionStep[];
	usage_metadata?: InteractionsUsageMetadata;
	error?: { code?: number; message?: string; status?: string };
}

export interface InteractionsUsageMetadata {
	prompt_token_count?: number;
	candidates_token_count?: number;
	thoughts_token_count?: number;
	total_token_count?: number;
	cached_content_token_count?: number;
}

// ---------------------------------------------------------------------------
// Computer Use action names (browser environment)
// ---------------------------------------------------------------------------

export type BrowserActionName =
	| "click"
	| "double_click"
	| "triple_click"
	| "middle_click"
	| "right_click"
	| "mouse_down"
	| "mouse_up"
	| "move"
	| "type"
	| "drag_and_drop"
	| "wait"
	| "press_key"
	| "key_down"
	| "key_up"
	| "hotkey"
	| "take_screenshot"
	| "scroll"
	| "go_back"
	| "navigate"
	| "go_forward";

export type MobileActionName =
	| "open_app"
	| "click"
	| "list_apps"
	| "wait"
	| "go_back"
	| "type"
	| "drag_and_drop"
	| "long_press"
	| "press_key"
	| "take_screenshot";

export type DesktopActionName =
	| "click"
	| "double_click"
	| "triple_click"
	| "middle_click"
	| "right_click"
	| "mouse_down"
	| "mouse_up"
	| "move"
	| "type"
	| "drag_and_drop"
	| "wait"
	| "press_key"
	| "key_down"
	| "key_up"
	| "hotkey"
	| "take_screenshot"
	| "scroll";

export type ComputerUseActionName = BrowserActionName | MobileActionName | DesktopActionName;
