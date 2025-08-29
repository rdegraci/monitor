# MACROS_README.md

# Macro Programming Tutorial

This document provides a step-by-step guide for writing and using macros in this app. It includes basic usage, syntax rules, and practical examples — including both simple macros and advanced TCL-enabled macros — with expected outputs.

## Table of Contents
1. Introduction to Macros
2. Macro Syntax
3. Step-by-Step Setup
4. Pure Macro Examples
5. TCL Macro Examples
6. Troubleshooting & Tips

---

## 1. Introduction to Macros
Macros in this app allow you to automate string expansion and computation. Macros can reference other macros and may include TCL scripting for advanced logic, math, conditionals, or formatting.

There are two types of macros:
- **Pure Macros**: Simple string substitution, possibly with nested expansion.
- **TCL Macros**: Code evaluated in an embedded TCL interpreter, with output captured and used as the macro result.

---

## 2. Macro Syntax

### Pure Macro Syntax
A macro is generally defined as a key→value pair, e.g. in your macro store or configuration:
```
hello_macro: "Hello, world!"
name_macro: "(user_name)"
greet_macro: "Hello, (name_macro)!"
```

Reference a macro by using its key (e.g., `(greet_macro)`). Macros may reference others recursively.

### TCL Macro Syntax
**Parenthesized TCL**: Surrounded by `(tcl ...)` 
- It will be executed as TCL code. The output of any `puts` in the TCL script becomes the macro expansion result.

**Examples:**
```
math_macro: "(tcl puts [expr {2 + 3 * 7}])"
date_macro: "(tcl puts [clock format [clock seconds] -format \"%Y-%m-%d\"]])"
```

---

## 3. Step-by-Step Setup

### Step 1: Define Your Macros
1. Locate or create the macro configuration/store file macros.json.
2. Add entries following the examples below.

### Step 2: Reference Macros
- In your templates, configuration, or code, use the macro names as appropriate. The macro system will expand them and include TCL results if relevant.

### Step 3: Reload or Use Macros
- If required, reload/restart the app or issue a reload command for changes to take effect.
- You can also use the built_in command:  :reload_macros

---

## 4. Pure Macro Examples

### Example 1: Simple Substitution
```
morning_macro: "Good morning!"
```
**Expanding `(morning_macro)` yields:**
```
Good morning!
```

### Example 2: Macro With Substitution
```
user_name: "Alex"
greet_user: "Hello, (user_name)!"
```
**Expanding `(greet_user)` yields:**
```
Hello, Alex!
```

### Example 3: Nested Macros
```
day: "Wednesday"
schedule: "Your meeting is scheduled for (day)."
```
**Expanding `(schedule)` yields:**
```
Your meeting is scheduled for Wednesday.
```

---

## 5. TCL Macro Examples

### Example 1: Math Calculation
```
math_macro: "(tcl set a 6; set b 3; puts [expr {$a * $b + 2}])"
```
**Expanding `(math_macro)` yields:**
```
20
```

### Example 2: Date/Time Output
```
date_macro: "(tcl puts [clock format [clock seconds] -format '%Y-%m-%d'])"
```
**Expanding `(date_macro)` yields (example):**
```
2024-06-08
```

### Example 3: Conditional Logic (using a macro variable)
```
is_prod: "0"
show_env: "(tcl if {${is_prod} == 1} {puts 'Production'} else {puts 'Development'})"
```
**Expanding `(show_env)` yields:**
```
Development
```

### Example 4: String Manipulation
```
repeated: "foo   bar   baz"
squash_spaces: "(tcl regsub -all { +} (repeated) { } result; puts $result)"
```
**Expanding `(squash_spaces)` yields:**
```
foo bar baz
```

---

## 6. Troubleshooting & Tips
- **Empty or Placeholder TCL Macros:** If the TCL code is empty or just `...`, the result will be blank and a warning will be logged.
- **TCL Errors:** If you have scripting errors, the macro will expand to `[TCL ERROR: ...]` with more details in the log.
- **Recursive Expansion:** Macro references like `(macro_name)` inside TCL bodies will be expanded before the TCL code runs.
- **Unsupported Features:** Only commands supported by standard TCL and available in the embedded interpreter will work.
- **Debugging:** Use logging (if enabled) to trace macro execution and diagnose problems.

---

For more examples or further guidance, refer to the code `lib/macro_utils.py` and tests in `tests/test_macro_utils.py`.