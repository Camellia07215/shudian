#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dlengine.py — 数字逻辑确定性引擎（DSH Skill: digital-logic-expert 的本地计算核心）

覆盖「分析 → 设计 → 调优 → 验证」全流程的确定性计算：
  analyze   逻辑表达式 -> 真值表 / 最小项 / 卡诺图 / 最简与或式(SOP) / 或与式(POS)
  design    真值表(最小项) -> 卡诺图化简 -> 多方案(与或 / 与非-与非 / 或非-或非) + Verilog + testbench
  hazard    静态冒险检测 + 冗余项消除建议
  verify    两个表达式/方案的全输入枚举等价性验证（全覆盖测试）
  evaluate  成本 / 复杂度 / 可靠性多维度评分

约定：
  变量为单个大写字母（A-Z）；支持运算符：
    NOT:  X'  ~X  !X     AND:  AB  A*B  A·B  A&B
    OR:   A+B  A|B       XOR:  A^B  A⊕B
  表达式可带 "F = ..." 左部，自动忽略。
仅使用标准库，Python >= 3.8。
"""

import argparse
import itertools
import json
import sys

MAX_VARS = 6  # 卡诺图与枚举的规模上限（6 变量 = 64 行真值表）


# ---------------------------------------------------------------------------
# 1. 表达式解析（递归下降）
# ---------------------------------------------------------------------------

class Node:
    def eval(self, env):
        raise NotImplementedError


class Var(Node):
    def __init__(self, name):
        self.name = name

    def eval(self, env):
        return env[self.name]


class Const(Node):
    def __init__(self, value):
        self.value = value

    def eval(self, env):
        return self.value


class Not(Node):
    def __init__(self, child):
        self.child = child

    def eval(self, env):
        return 1 - self.child.eval(env)


class Bin(Node):
    def __init__(self, op, left, right):
        self.op, self.left, self.right = op, left, right

    def eval(self, env):
        a, b = self.left.eval(env), self.right.eval(env)
        if self.op == "and":
            return a & b
        if self.op == "or":
            return a | b
        return a ^ b  # xor


def tokenize(expr):
    tokens, i = [], 0
    while i < len(expr):
        c = expr[i]
        if c.isspace():
            i += 1
            continue
        if c.isalpha():
            tokens.append(("VAR", c.upper()))
            i += 1
        elif c.isdigit():
            tokens.append(("CONST", int(c)))
            i += 1
        elif c in "~!":
            tokens.append(("NOT", c)); i += 1
        elif c == "'":
            tokens.append(("POSTNOT", c)); i += 1
        elif c in "*·&":
            tokens.append(("AND", c)); i += 1
        elif c in "+|":
            tokens.append(("OR", c)); i += 1
        elif c in "^⊕":
            tokens.append(("XOR", c)); i += 1
        elif c == "(":
            tokens.append(("LP", c)); i += 1
        elif c == ")":
            tokens.append(("RP", c)); i += 1
        else:
            raise ValueError("无法识别的字符: %r" % c)
    return tokens


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None)

    def eat(self, kind=None):
        tok = self.peek()
        if kind and tok[0] != kind:
            raise ValueError("语法错误：期望 %s，得到 %s" % (kind, tok))
        self.pos += 1
        return tok

    def parse(self):
        node = self.parse_or()
        if self.pos != len(self.tokens):
            raise ValueError("表达式末尾有多余内容：%s" % (self.tokens[self.pos:],))
        return node

    def parse_or(self):
        node = self.parse_xor()
        while self.peek()[0] == "OR":
            self.eat()
            node = Bin("or", node, self.parse_xor())
        return node

    def parse_xor(self):
        node = self.parse_and()
        while self.peek()[0] == "XOR":
            self.eat()
            node = Bin("xor", node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_unary()
        while True:
            kind, _ = self.peek()
            if kind == "AND":
                self.eat()
                node = Bin("and", node, self.parse_unary())
            elif kind in ("VAR", "CONST", "LP", "NOT"):  # 并置 = 与
                node = Bin("and", node, self.parse_unary())
            else:
                return node

    def parse_unary(self):
        if self.peek()[0] == "NOT":
            self.eat()
            return Not(self.parse_unary())
        node = self.parse_atom()
        while self.peek()[0] == "POSTNOT":  # X'
            self.eat()
            node = Not(node)
        return node

    def parse_atom(self):
        kind, val = self.peek()
        if kind == "VAR":
            self.eat()
            return Var(val)
        if kind == "CONST":
            self.eat()
            if val not in (0, 1):
                raise ValueError("逻辑常量只能是 0 或 1")
            return Const(val)
        if kind == "LP":
            self.eat()
            node = self.parse_or()
            self.eat("RP")
            return node
        raise ValueError("语法错误：意外的记号 %s" % ((kind, val),))


def collect_vars(node, acc=None):
    if acc is None:
        acc = set()
    if isinstance(node, Var):
        acc.add(node.name)
    elif isinstance(node, (Not,)):
        collect_vars(node.child, acc)
    elif isinstance(node, Bin):
        collect_vars(node.left, acc)
        collect_vars(node.right, acc)
    return acc


def parse_expr(text):
    text = text.strip()
    if "=" in text:  # 去掉 "F = " 左部
        text = text.split("=", 1)[1]
    tokens = tokenize(text)
    if not tokens:
        raise ValueError("空表达式")
    return Parser(tokens).parse()


# ---------------------------------------------------------------------------
# 2. 真值表 / 最小项
# ---------------------------------------------------------------------------

def truth_table(node, variables):
    rows = []
    for bits in itertools.product([0, 1], repeat=len(variables)):
        env = dict(zip(variables, bits))
        rows.append((bits, node.eval(env)))
    return rows


def minterms_of(rows):
    return [i for i, (_, v) in enumerate(rows) if v == 1]


def render_truth_table(rows, variables, out_name):
    lines = []
    header = " | ".join(variables) + " || " + out_name
    lines.append(header)
    lines.append("-" * len(header))
    for bits, v in rows:
        lines.append(" | ".join(str(b) for b in bits) + " || %d" % v)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. Quine-McCluskey 化简（SOP），POS 通过对反函数化简得到
# ---------------------------------------------------------------------------

def term_str(bits, variables):
    """('-' 表示已消去) -> 字面量字符串，如 A'BC"""
    s = "".join(v if b == "1" else (v + "'" if b == "0" else "")
                for v, b in zip(variables, bits))
    return s if s else "1"


def covers(term, minterm_bits):
    """term 为 '01-' 形式字符串；minterm_bits 为等长 0/1 字符串或整数序列。"""
    return all(t == "-" or t == str(b) for t, b in zip(term, minterm_bits))


def qm_minimize(num_vars, minterms, dontcares=()):
    """返回覆盖 minterms 的最简主蕴含项列表（每项为 '01-' 形式字符串）。"""
    all_terms = sorted(set(minterms) | set(dontcares))
    if not all_terms:
        return []
    if len(all_terms) == (1 << num_vars):  # 恒 1
        return ["-" * num_vars]
    current = [format(m, "0%db" % num_vars) for m in all_terms]
    primes = []
    while current:
        merged = set()
        used = [False] * len(current)
        nxt = set()
        for i in range(len(current)):
            for j in range(i + 1, len(current)):
                a, b = current[i], current[j]
                diff = [k for k in range(num_vars) if a[k] != b[k]]
                if len(diff) == 1 and not (a[diff[0]] == "-" or b[diff[0]] == "-"):
                    k = diff[0]
                    merged.add(a[:k] + "-" + a[k + 1:])
                    used[i] = used[j] = True
        for i, t in enumerate(current):
            if not used[i]:
                primes.append(t)
        current = sorted(merged)
        if not merged:
            break
    primes = sorted(set(primes))

    # 精确覆盖：贪心 + 回溯求精（规模小，足够课程场景）
    on_bits = {m: format(m, "0%db" % num_vars) for m in minterms}
    def cover_set(term):
        return {m for m in minterms if covers(term, on_bits[m])}
    cover_map = {t: cover_set(t) for t in primes}
    uncovered = set(minterms)
    chosen = []
    # 必要主蕴含项
    for m in minterms:
        ts = [t for t in primes if m in cover_map[t]]
        if len(ts) == 1:
            if ts[0] not in chosen:
                chosen.append(ts[0])
    for t in chosen:
        uncovered -= cover_map[t]
    # 剩余用分支定界求最小覆盖
    best = [None]

    def dfs(rem, cur):
        if not rem:
            cand = [t for t in primes if t in cur]
            if best[0] is None or len(cand) < len(best[0]):
                best[0] = cand
            return
        if best[0] is not None and len(cur) >= len(best[0]):
            return
        m = min(rem, key=lambda x: sum(1 for t in primes if x in cover_map[t]))
        for t in primes:
            if m in cover_map[t]:
                dfs(rem - cover_map[t], cur | {t})
    if uncovered:
        best[0] = list(chosen) + [t for t in primes if t not in chosen]  # 上界
        dfs(uncovered, set(chosen))
        return sorted(set(best[0]), key=lambda t: (t.count("-"), t))
    return sorted(set(chosen), key=lambda t: (t.count("-"), t))


def sop_of_terms(terms, variables):
    return " + ".join(term_str(t, variables) for t in terms) if terms else "0"


def pos_from_sop_of_complement(comp_terms, variables):
    """F' 的 SOP -> F 的 POS（德摩根）。返回和项列表。"""
    sums = []
    for t in comp_terms:
        lits = []
        for v, b in zip(variables, t):
            if b == "1":
                lits.append(v + "'")
            elif b == "0":
                lits.append(v)
        sums.append("(" + "+".join(lits) + ")" if lits else "0")
    return sums


# ---------------------------------------------------------------------------
# 4. 卡诺图文本渲染（2-4 变量）
# ---------------------------------------------------------------------------

def gray(n):
    return [i ^ (i >> 1) for i in range(1 << n)]


def render_kmap(num_vars, values, variables):
    """values: 长度为 2^num_vars 的 0/1/d 列表（d = 无关项）"""
    if num_vars == 2:
        rows_vars, cols_vars = variables[:1], variables[1:]
    elif num_vars == 3:
        rows_vars, cols_vars = variables[:1], variables[1:]
    elif num_vars == 4:
        rows_vars, cols_vars = variables[:2], variables[2:]
    else:
        return "(变量数 >4，卡诺图从略，化简结果仍由 Quine-McCluskey 算法精确给出)"
    nr, nc = len(rows_vars), len(cols_vars)
    row_codes = gray(nr)
    col_codes = gray(nc)
    lines = []
    head = "%s\\%s" % ("".join(rows_vars), "".join(cols_vars))
    col_labels = [format(c, "0%db" % nc) for c in col_codes]
    lines.append(head.ljust(6) + "  ".join(col_labels))
    for r in row_codes:
        row_label = format(r, "0%db" % nr)
        cells = []
        for c in col_codes:
            idx = (r << nc) | c
            cells.append(str(values[idx]))
        lines.append(row_label.ljust(6) + "  ".join(cells))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. 静态冒险检测（静态 1 冒险：相邻最小项未被同一蕴含项共同覆盖）
# ---------------------------------------------------------------------------

def detect_static1_hazards(sop_terms, num_vars, minterms):
    """返回 [(跳变输入组合描述, 变化变量, 建议冗余项字符串)]"""
    on_bits = {m: format(m, "0%db" % num_vars) for m in minterms}
    hazards = []
    seen = set()
    for m1 in minterms:
        for k in range(num_vars):
            m2 = m1 ^ (1 << (num_vars - 1 - k))
            if m2 not in on_bits or m2 < m1:
                continue
            jointly = any(covers(t, on_bits[m1]) and covers(t, on_bits[m2]) for t in sop_terms)
            if jointly:
                continue
            key = (min(m1, m2), max(m1, m2))
            if key in seen:
                continue
            seen.add(key)
            # 冗余项 = 两最小项公共固定部分
            common = "".join(a if a == b else "-" for a, b in zip(on_bits[m1], on_bits[m2]))
            hazards.append((on_bits[m1], on_bits[m2], k, common))
    return hazards


# ---------------------------------------------------------------------------
# 6. 成本 / 延迟 / 评分
# ---------------------------------------------------------------------------

def cost_model(sop_terms, variables):
    n_terms = len(sop_terms)
    lit_counts = [sum(1 for b in t if b != "-") for t in sop_terms]
    and_gates = sum(1 for c in lit_counts if c >= 2)  # 单字面量项直连，无需与门
    or_gates = 1 if n_terms > 1 else 0
    inv = len({v for t in sop_terms for v, b in zip(variables, t) if b == "0"})
    gates = and_gates + or_gates + inv
    inputs = sum(c for c in lit_counts if c >= 2) + (n_terms if or_gates else 0) + inv
    if gates == 0:
        delay = 0
    elif and_gates and or_gates:
        delay = 2
    else:
        delay = 1
    delay += 1 if inv else 0
    return {"and": and_gates, "or": or_gates, "not": inv,
            "gate_total": gates, "input_total": inputs,
            "delay_levels": delay}


def evaluate_design(sop_terms, variables, num_vars, minterms):
    cost = cost_model(sop_terms, variables)
    hazards = detect_static1_hazards(sop_terms, num_vars, minterms)
    # 评分：成本(30) 复杂度(30) 可靠性(40)——可靠性权重最高：毛刺对时序负载是致命的
    cost_score = max(0, 30 - 2 * cost["gate_total"] - cost["input_total"])
    complexity_score = max(0, 30 - 5 * len(sop_terms) - 2 * (cost["delay_levels"] - 2))
    reliability_score = 40 - 15 * len(hazards)
    total = cost_score + complexity_score + max(0, reliability_score)
    return {
        "cost": cost,
        "hazard_count": len(hazards),
        "scores": {"硬件成本": cost_score, "电路复杂度": complexity_score,
                   "运行可靠性": max(0, reliability_score)},
        "total": total,
        "grade": ("优秀" if total >= 85 else "良好" if total >= 70 else
                  "合格" if total >= 60 else "需优化"),
    }


# ---------------------------------------------------------------------------
# 7. Verilog 生成
# ---------------------------------------------------------------------------

def verilog_literal(v, b):
    return v if b == "1" else ("~" + v)


def gen_verilog(module_name, variables, sop_terms, out_name):
    prods = []
    for t in sop_terms:
        lits = [verilog_literal(v, b) for v, b in zip(variables, t) if b != "-"]
        prods.append("(" + " & ".join(lits) + ")" if lits else "1'b1")
    expr = " | ".join(prods) if prods else "1'b0"
    ports = ", ".join(variables + [out_name])
    lines = [
        "// 由 digital-logic-expert (dlengine) 自动生成",
        "module %s(%s);" % (module_name, ports),
        "    input  %s;" % ", ".join(variables),
        "    output %s;" % out_name,
        "    assign %s = %s;" % (out_name, expr),
        "endmodule",
    ]
    return "\n".join(lines)


def gen_testbench(module_name, variables, minterms, out_name):
    n = len(variables)
    concat = ", ".join(variables)
    conns = ", ".join(".%s(%s)" % (p, p) for p in variables + [out_name])
    tb = [
        "// 全覆盖 testbench：枚举全部 %d 种输入组合" % (1 << n),
        "`timescale 1ns/1ps",
        "module %s_tb;" % module_name,
        "    reg  %s;" % concat,
        "    wire %s;" % out_name,
        "    %s dut(%s);" % (module_name, conns),
        "    integer i;",
        "    initial begin",
        "        for (i = 0; i < %d; i = i + 1) begin" % (1 << n),
        "            {%s} = i[%d:0];" % (concat, n - 1),
        "            #10;",
        "            $display(\"%s = %%b -> %s = %%b\", {%s}, %s);" % (
                concat, out_name, concat, out_name),
        "        end",
        "        $display(\"Simulation done.\");",
        "        $finish;",
        "    end",
        "endmodule",
    ]
    return "\n".join(tb)


# ---------------------------------------------------------------------------
# 8. 命令实现
# ---------------------------------------------------------------------------

def fmt_minterm_list(ms):
    return "Σm(%s)" % ",".join(str(m) for m in ms) if ms else "(空)"


def cmd_analyze(args):
    node = parse_expr(args.expr)
    variables = sorted(collect_vars(node))
    if len(variables) > MAX_VARS:
        raise SystemExit("变量数超过上限 %d" % MAX_VARS)
    rows = truth_table(node, variables)
    ms = minterms_of(rows)
    n = len(variables)
    values = [v for _, v in rows]
    terms = qm_minimize(n, ms)
    sop = sop_of_terms(terms, variables)

    print("=" * 60)
    print("【电路分析结果】表达式: %s" % args.expr)
    print("=" * 60)
    print("\n■ 输入变量: %s   输出: %s" % (", ".join(variables), args.name))
    print("\n■ 真值表")
    print(render_truth_table(rows, variables, args.name))
    print("\n■ 最小项: %s" % fmt_minterm_list(ms))
    print("\n■ 卡诺图")
    print(render_kmap(n, values, variables))
    print("\n■ 最简与或式 (SOP):")
    print("  %s = %s" % (args.name, sop))
    if ms and len(ms) < (1 << n):
        comp = qm_minimize(n, [m for m in range(1 << n) if m not in ms])
        pos = pos_from_sop_of_complement(comp, variables)
        print("\n■ 最简或与式 (POS):")
        print("  %s = %s" % (args.name, "".join(pos)))
    haz = detect_static1_hazards(terms, n, ms)
    print("\n■ 冒险检查: %s" % ("无静态 1 冒险" if not haz
                               else "发现 %d 处静态 1 冒险（用 hazard 子命令查看详情）" % len(haz)))
    print("\n■ 等价性自检: 化简结果与原表达式全输入枚举比对 ...", end=" ")
    ok = all(parse_expr(sop).eval(dict(zip(variables, bits))) == v for bits, v in rows) if ms else True
    print("通过 ✓" if ok else "不通过 ✗")
    ev = evaluate_design(terms, variables, n, ms)
    print("\n■ 方案评估: 门数 %d，输入端 %d，延迟 %d 级；综合评分 %d (%s)"
          % (ev["cost"]["gate_total"], ev["cost"]["input_total"],
             ev["cost"]["delay_levels"], ev["total"], ev["grade"]))


def cmd_design(args):
    variables = [v.strip().upper() for v in args.vars.split(",") if v.strip()]
    n = len(variables)
    if n < 1 or n > MAX_VARS:
        raise SystemExit("变量数需在 1-%d 之间" % MAX_VARS)
    ms = [int(x) for x in args.minterms.split(",") if x.strip()] if args.minterms else []
    dc = [int(x) for x in args.dontcares.split(",") if x.strip()] if args.dontcares else []
    for m in ms + dc:
        if not (0 <= m < (1 << n)):
            raise SystemExit("最小项 %d 超出 %d 变量范围 [0, %d]" % (m, n, (1 << n) - 1))

    values = ["1" if i in ms else ("d" if i in dc else "0") for i in range(1 << n)]
    terms = qm_minimize(n, ms, dc)
    sop = sop_of_terms(terms, variables)
    comp = qm_minimize(n, [i for i in range(1 << n) if i not in ms and i not in dc], dc)
    pos = pos_from_sop_of_complement(comp, variables)

    print("=" * 60)
    print("【电路设计结果】%s  变量: %s  最小项: %s" % (args.module, ", ".join(variables), fmt_minterm_list(ms)))
    print("=" * 60)
    if dc:
        print("无关项: Σd(%s)" % ",".join(map(str, dc)))
    print("\n■ 卡诺图")
    print(render_kmap(n, values, variables))
    print("\n■ 卡诺图化简结果（最简与或式 SOP）:")
    print("  F = %s" % sop)
    print("\n■ 多实现方案:")
    print("  方案一（与或式，直接 SOP）:")
    print("    F = %s" % sop)
    nand_terms = [term_str(t, variables) for t in terms]
    if len(nand_terms) > 1:
        nand_expr = "((" + ")' · (".join(nand_terms) + ")')'"
    elif nand_terms:
        nand_expr = "(%s)''" % nand_terms[0]
    else:
        nand_expr = "0"
    print("  方案二（与非-与非式，全部用 NAND 实现）:")
    print("    F = %s" % nand_expr)
    print("  方案三（或非-或非式，全部用 NOR 实现，由 POS 两次取反转换）:")
    if pos:
        print("    F = (%s)''" % " + ".join(pos))
        print("    其中 POS 形式 F = %s" % "".join(pos))
    else:
        print("    F = 0")

    haz = detect_static1_hazards(terms, n, ms)
    print("\n■ 调优检查:")
    if haz:
        for b1, b2, k, common in haz:
            print("  ⚠ 静态 1 冒险：输入 %s ↔ %s（变量 %s 变化时），建议增加冗余项 %s"
                  % (b1, b2, variables[k], term_str(common, variables)))
    else:
        print("  ✓ 无静态冒险，无需添加冗余项")
    ev = evaluate_design(terms, variables, n, ms)
    print("  成本：与门 %d / 或门 %d / 非门 %d，共 %d 门，%d 个输入端，延迟 %d 级"
          % (ev["cost"]["and"], ev["cost"]["or"], ev["cost"]["not"],
             ev["cost"]["gate_total"], ev["cost"]["input_total"], ev["cost"]["delay_levels"]))
    print("  评分：硬件成本 %d / 电路复杂度 %d / 运行可靠性 %d → 综合 %d 分（%s）"
          % (ev["scores"]["硬件成本"], ev["scores"]["电路复杂度"],
             ev["scores"]["运行可靠性"], ev["total"], ev["grade"]))

    print("\n■ Verilog 实现")
    print(gen_verilog(args.module, variables, terms, "F"))
    print("\n■ 全覆盖 Testbench")
    print(gen_testbench(args.module, variables, ms, "F"))

    print("\n■ 自动验证（化简结果 vs 真值表，全 %d 种输入）: " % (1 << n), end="")
    if ms:
        sop_node = parse_expr(sop)
        ok = all(sop_node.eval(dict(zip(variables, map(int, format(i, "0%db" % n))))) == 1
                 for i in ms)
        zeros_ok = all(sop_node.eval(dict(zip(variables, map(int, format(i, "0%db" % n))))) == 0
                       for i in range(1 << n) if i not in ms and i not in dc)
        print("通过 ✓" if ok and zeros_ok else "不通过 ✗")
    else:
        print("通过 ✓（恒 0）")


def cmd_hazard(args):
    node = parse_expr(args.expr)
    variables = sorted(collect_vars(node))
    n = len(variables)
    rows = truth_table(node, variables)
    ms = minterms_of(rows)
    terms = qm_minimize(n, ms)
    print("表达式: %s" % args.expr)
    print("最简 SOP: F = %s" % sop_of_terms(terms, variables))
    haz = detect_static1_hazards(terms, n, ms)
    if not haz:
        print("检测结果：无静态 1 冒险 ✓")
        return
    print("检测结果：发现 %d 处静态 1 冒险 ⚠" % len(haz))
    fixed = list(terms)
    for b1, b2, k, common in haz:
        print("  - 输入 %s ↔ %s，变量 %s 变化时输出可能出现毛刺" % (b1, b2, variables[k]))
        print("    消除方案：添加冗余项 %s" % term_str(common, variables))
        if common not in fixed:
            fixed.append(common)
    print("\n消险后的稳健表达式：")
    print("  F = %s" % sop_of_terms(sorted(set(fixed)), variables))
    print("（依据：共识定理——增加共识项可消除相邻最小项跳变引起的静态冒险）")


def cmd_verify(args):
    n1 = parse_expr(args.expr1)
    n2 = parse_expr(args.expr2)
    variables = sorted(collect_vars(n1) | collect_vars(n2))
    if len(variables) > MAX_VARS:
        raise SystemExit("变量数超过上限 %d" % MAX_VARS)
    total = 1 << len(variables)
    bad = []
    for bits in itertools.product([0, 1], repeat=len(variables)):
        env = dict(zip(variables, bits))
        if n1.eval(env) != n2.eval(env):
            bad.append(env)
    print("全覆盖验证：共 %d 种输入组合" % total)
    if not bad:
        print("结果：两表达式功能完全等价 ✓ (%d/%d 通过)" % (total, total))
    else:
        print("结果：不等价 ✗，失配 %d 处：" % len(bad))
        for env in bad[:10]:
            print("  失配输入: %s" % env)


def sop_terms_as_written(node, variables):
    """若表达式本身就是与或式（SOP），按书写结构提取乘积项（'01-' 形式）；
    否则返回 None（调用方退化为化简结果）。"""
    def literal_bits(t):
        bits = {v: "-" for v in variables}
        lits = []

        def collect(n):
            if isinstance(n, Var):
                lits.append((n.name, "1")); return True
            if isinstance(n, Not) and isinstance(n.child, Var):
                lits.append((n.child.name, "0")); return True
            if isinstance(n, Bin) and n.op == "and":
                return collect(n.left) and collect(n.right)
            return False

        if not collect(t):
            return None
        for v, b in lits:
            bits[v] = b
        return "".join(bits[v] for v in variables)

    or_terms = []

    def split_or(n):
        if isinstance(n, Bin) and n.op == "or":
            split_or(n.left); split_or(n.right)
        else:
            or_terms.append(n)
    split_or(node)

    terms = [literal_bits(t) for t in or_terms]
    return terms if all(t is not None for t in terms) else None


def cmd_evaluate(args):
    node = parse_expr(args.expr)
    variables = sorted(collect_vars(node))
    n = len(variables)
    rows = truth_table(node, variables)
    ms = minterms_of(rows)
    min_terms = qm_minimize(n, ms)
    # 评估对象优先取"原式书写结构"（保留冗余项），非 SOP 时退化为最简式
    terms = sop_terms_as_written(node, variables) or min_terms
    ev = evaluate_design(terms, variables, n, ms)
    print(json.dumps({"expression": args.expr,
                      "evaluated_form": sop_of_terms(terms, variables),
                      "minimized_sop": sop_of_terms(min_terms, variables),
                      **ev}, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(
        prog="dlengine",
        description="数字逻辑确定性引擎：分析/设计/调优/验证/评估全流程")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="分析逻辑表达式：真值表/卡诺图/化简/冒险/评估")
    a.add_argument("--expr", required=True, help="逻辑表达式，如 \"F = AB + A'C\"")
    a.add_argument("--name", default="F", help="输出信号名，默认 F")
    a.set_defaults(fn=cmd_analyze)

    d = sub.add_parser("design", help="由真值表设计电路：多方案 + Verilog + 调优 + 验证")
    d.add_argument("--vars", required=True, help="变量列表，如 A,B,C")
    d.add_argument("--minterms", default="", help="最小项编号，如 3,5,6,7")
    d.add_argument("--dontcares", default="", help="无关项编号，可空")
    d.add_argument("--module", default="logic_design", help="Verilog 模块名")
    d.set_defaults(fn=cmd_design)

    h = sub.add_parser("hazard", help="静态冒险检测与冗余项消除建议")
    h.add_argument("--expr", required=True)
    h.set_defaults(fn=cmd_hazard)

    v = sub.add_parser("verify", help="两个表达式的全输入枚举等价性验证")
    v.add_argument("--expr1", required=True)
    v.add_argument("--expr2", required=True)
    v.set_defaults(fn=cmd_verify)

    e = sub.add_parser("evaluate", help="方案多维度评分（JSON 输出）")
    e.add_argument("--expr", required=True)
    e.set_defaults(fn=cmd_evaluate)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
