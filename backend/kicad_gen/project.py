# -*- coding: utf-8 -*-
"""生成 KiCad 工程文件 (.kicad_pro) 及符号/封装库表"""

from __future__ import annotations

import uuid


def _u():
    return str(uuid.uuid4())


def build_project(name, title="Untitled"):
    """生成 .kicad_pro 工程文件内容"""
    return f"""{{
  "board": {{
    "active_layer": 0,
    "active_layer_preset": "",
    "auto_track_width": true,
    "hidden_netclasses": [],
    "hidden_nets": [],
    "locked": false,
    "net_colors": null,
    "solder_mask": null,
    "visible_layers": "fffffff_ffffffff",
    "visible_items": []
  }},
  "board_commit_hash": "",
  "boards": [],
  "cvpcb": {{
    "equivalence_files": []
  }},
  "erl_version": 0,
  "libraries": {{
    "pinned_footprint_libs": [],
    "pinned_symbol_libs": []
  }},
  "meta": {{
    "filename": "{name}.kicad_pro",
    "version": 1
  }},
  "net_settings": {{
    "classes": [
      {{
        "bus_width": 12,
        "clearance": 0.2,
        "diff_pair_gap": 0.25,
        "diff_pair_via_gap": 0.25,
        "diff_pair_width": 0.2,
        "line_style": 0,
        "microvia_diameter": 0.3,
        "microvia_drill": 0.1,
        "name": "Default",
        "pcb_color": "rgba(0, 0, 0, 0.000)",
        "schematic_color": "rgba(0, 0, 0, 0.000)",
        "track_width": 0.25,
        "via_diameter": 0.8,
        "via_drill": 0.4,
        "wire_width": 6
      }}
    ],
    "meta": {{
      "version": 3
    }},
    "net_colors": null,
    "netclass_assignments": null,
    "netclass_patterns": []
  }},
  "pcbnew": {{
    "last_paths": {{
      "gencad": "",
      "idf": "",
      "netlist": "",
      "plot": "",
      "pos_files": "",
      "specctra_dsn": "",
      "svg": "",
      "vrml": ""
    }},
    "page_layout_descr_file": ""
  }},
  "schematic": {{
    "annotate_start_num": 0,
    "bom_export_filename": "",
    "bom_fmt_presets": [],
    "bom_fmt_settings": {{}},
    "bom_plugins": [],
    "bom_presets": [],
    "drawing": {{
      "dashed_lines_dash_length_ratio": 12.0,
      "dashed_lines_gap_length_ratio": 3.0,
      "default_line_thickness": 6.0,
      "default_text_size": 50.0,
      "field_names": [],
      "intersheets_ref_show": false,
      "intersheets_ref_suffix": "",
      "junction_size_choice": 3,
      "label_size_ratio": 0.375,
      "operating_point_overlay_i_precision": 3,
      "operating_point_overlay_v_precision": 3,
      "overlay_offset_x": 0.0,
      "pin_symbol_size": 0.0,
      "text_offset_ratio": 0.15
    }},
    "legacy_lib_dir": "",
    "legacy_lib_list": [],
    "meta": {{
      "version": 1
    }},
    "net_format_name": "",
    "page_layout_descr_file": "",
    "plot_directory": "",
    "spice_current_sheet_as_root": false,
    "spice_external_command": "spice \"%I\"",
    "subpart_first_id": 65,
    "subpart_id_separator": 0
  }},
  "sheets": [
    [
      "{_u()}",
      ""
    ]
  ],
  "text_variables": {{
    "PROJECT_NAME": "{title}"
  }}
}}
"""


def build_sym_lib_table(project_name):
    """生成 sym-lib-table（空表，符号全部内嵌在原理图中）"""
    return f"""(sym_lib_table
  (version 7)
)
"""


def build_fp_lib_table():
    """生成工程级 fp-lib-table（空表，让 KiCad 使用自带的全局封装库表）。

    v2.0.2 修复：旧版写死 ``${KICAD8_FOOTPRINT_DIR}``，在 KiCad 9/10 上该变量
    不存在（分别叫 KICAD9_/KICAD10_FOOTPRINT_DIR），工程级表反而会遮蔽全局表，
    导致标准封装（Resistor_SMD 等）找不到。留空即可跨 8/9/10 通用。
    """
    return """(fp_lib_table
  (version 7)
)
"""
