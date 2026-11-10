import {basicSetup, EditorView} from "codemirror";
import {EditorState, Prec} from "@codemirror/state";
import {keymap, placeholder} from "@codemirror/view";
import {indentService, indentUnit, StreamLanguage, syntaxTree} from "@codemirror/language";
import {completeFromList} from "@codemirror/autocomplete";
import {python, pythonLanguage} from "@codemirror/lang-python";
import {vscodeDark} from "@uiw/codemirror-theme-vscode";

const modelCommands = [
  "let", "fn", "for", "if", "part", "use", "include", "group", "end",
  "property", "invisible", "position", "euler", "quaternion", "scale", "material", "tessellation",
  "box", "sphere", "cylinder", "cone", "torus", "pyramid", "cylindrical_box", "partial_sphere",
  "partial_cone", "partial_cylinder", "partial_torus", "ellipsoid", "sphere_no_pole",
  "plane", "planar_circle", "profile", "polygon", "spline", "extrude", "revolve",
  "union", "subtract", "intersect", "faces", "offset", "shell", "chamfer", "fillet",
];
const animationCommands = ["animation", "track", "key", "cycle", "for", "end"];
const mathFunctions = new Set([
  "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "exp", "log", "sqrt",
  "abs", "radians", "degrees",
]);

function commandLanguage(commands, blockStarts, modifiers, ignoreCase = false) {
  const keywords = new Set(commands);
  const complete = completeFromList(commands.map(label => ({label, type: "keyword"})));
  const language = StreamLanguage.define({
    languageData: {
      commentTokens: {line: "#"},
      indentOnInput: ignoreCase ? /^\s*end$/i : /^\s*end$/,
      autocomplete(context) {
        const line = context.state.doc.lineAt(context.pos);
        const prefix = line.text.slice(0, context.pos - line.from);
        return /^\s*[a-z_]*$/i.test(prefix) ? complete(context) : null;
      },
    },
    token(stream) {
      const atCommand = /^\s*$/.test(stream.string.slice(0, stream.pos));
      if (stream.eatSpace()) return null;
      if (stream.peek() === "#") {
        stream.skipToEnd();
        return "comment";
      }
      if (stream.match(/^(?:"(?:\\.|[^"\\])*"?|'(?:\\.|[^'\\])*'?|`[^`]*`?)/)) return "string";
      if (stream.match(/^(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?/i)) return "number";
      if (stream.match(/^[a-z_][a-z_0-9]*/i)) {
        const word = ignoreCase ? stream.current().toLowerCase() : stream.current();
        if (atCommand && keywords.has(word) || modifiers.has(word)) return "keyword";
        if (mathFunctions.has(word)) return "function";
        if (["pi", "e", "true", "false", "null"].includes(word)) return "atom";
        return "variableName";
      }
      if (stream.eat(/[+*/%<>=!$-]/)) return "operator";
      stream.next();
      return null;
    },
  });

  return [
    language,
    indentUnit.of("  "),
    indentService.of((context, pos) => {
      const line = context.lineAt(pos);
      if (!line.from) return 0;
      let previous = context.lineAt(line.from - 1);
      while (previous.from && /^\s*(?:#.*)?$/.test(previous.text)) {
        previous = context.lineAt(previous.from - 1);
      }
      const command = previous.text.trimStart().match(/^\w+/)?.[0] ?? "";
      const opens = blockStarts.includes(ignoreCase ? command.toLowerCase() : command);
      const closes = (ignoreCase ? /^\s*end\b/i : /^\s*end\b/).test(line.text);
      return Math.max(0, context.lineIndent(previous.from) + context.unit * (Number(opens) - Number(closes)));
    }),
  ];
}

const textLanguage = commandLanguage(
  modelCommands, ["for", "if", "part", "group", "profile"], new Set(["in", "range", "as", "default"]), true,
);
const animationLanguage = commandLanguage(
  animationCommands, ["animation", "track", "for"], new Set(["loop", "position", "euler", "scale", "in", "range"]),
);

const pythonApi = [
  ["create_box", "(origin, length, width, height)"],
  ["create_sphere", "(center, radius)"],
  ["create_cylinder", "(base, radius, height, axis=None)"],
  ["boolean_union", "(a, b)"],
  ["boolean_difference", "(a, b)"],
  ["boolean_intersection", "(a, b)"],
  ...[
    "create_profile", "create_spline_profile", "create_extrude", "create_revolve",
    "create_cone", "create_torus", "create_pyramid", "create_cylindrical_box",
    "create_partial_sphere", "create_partial_cone", "create_partial_cylinder", "create_partial_torus",
    "create_ellipsoid", "create_sphere_no_pole", "create_plane", "create_planar_circle",
    "chamfer_fillet", "circular_fillet", "face_info", "offset_brep", "shell_brep", "transform_brep", "tessellate",
  ].map(label => [label]),
].map(([label, detail]) => ({label, detail, type: "function"}));

const pythonExtensions = [
  python(),
  indentUnit.of("    "),
  pythonLanguage.data.of({
    autocomplete(context) {
      const match = context.matchBefore(/\bsm\.(?:[a-z_]\w*)?$/i);
      if (!match) return null;
      // The start of sm is outside a property node, but inside any enclosing comment or string.
      for (let node = syntaxTree(context.state).resolveInner(match.from, 1); node; node = node.parent) {
        if (/Comment|String/.test(node.name)) return null;
      }
      return {from: match.from + 3, options: pythonApi, validFor: /^\w*$/};
    },
  }),
];

const editorTheme = EditorView.theme({
  "&": {flex: "1", minWidth: "0", height: "100%", fontSize: "13px"},
  "&.cm-focused": {outline: "none", boxShadow: "inset 0 0 0 1px #57b7d9"},
  ".cm-scroller": {
    lineHeight: "1.55", overscrollBehavior: "contain", userSelect: "text", WebkitUserSelect: "text",
  },
  ".cm-content, .cm-gutter": {paddingTop: "12px", paddingBottom: "12px"},
  ".cm-line": {paddingLeft: "8px", paddingRight: "8px"},
});

const editors = new Map();

function sync(textarea, mode, preview) {
  let editor = editors.get(textarea);
  if (editor?.mode === mode && editor.view.state.doc.toString() === textarea.value) return;

  const language = mode === "animation" ? animationLanguage : mode === "python" ? pythonExtensions : textLanguage;
  const extensions = [
    basicSetup, vscodeDark, editorTheme, language,
    EditorView.contentAttributes.of({
      "aria-label": textarea.getAttribute("aria-label"),
      spellcheck: "false", autocapitalize: "off", autocorrect: "off",
    }),
    EditorView.updateListener.of(update => {
      if (update.docChanged) {
        textarea.value = update.state.doc.toString();
        // Draft saving and chat revision checks share the original input event.
        textarea.dispatchEvent(new Event("input", {bubbles: true}));
      }
    }),
  ];
  if (textarea.placeholder) extensions.push(placeholder(textarea.placeholder));
  if (preview) {
    extensions.push(Prec.high(keymap.of([{
      key: "Mod-Enter", run() { preview(); return true; },
    }, {
      key: "Ctrl-Enter", run() { preview(); return true; },
    }])));
  }

  // A loaded sample, file or chat result starts a fresh undo history.
  const state = EditorState.create({doc: textarea.value, extensions});
  if (editor) {
    editor.view.setState(state);
    editor.mode = mode;
  } else {
    const parent = textarea.parentElement;
    const view = new EditorView({state, parent});
    parent.classList.add("cm-mounted");
    editors.set(textarea, {view, mode});
  }
}

globalThis.CadSourceEditor = {sync};
