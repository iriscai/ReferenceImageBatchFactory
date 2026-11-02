window.PIC_FACTORY_BLUEPRINT = {
  project: {
    name: "picfactory_newproject_v1",
    version: "0.1.0",
    default_language: "zh-CN",
    default_export_format: "json",
    image_base_path: "/assets/previews/",
    enable_rules_engine: true,
    enable_frontend_presets: true
  },
  groups: [
    { id: "base", label: "系统基础" },
    { id: "character", label: "人物矩阵" },
    { id: "style", label: "风格 / UI" },
    { id: "story", label: "叙事 / 场景" },
    { id: "rules", label: "规则 / 前台 / 导出" }
  ],
  presets: [
    {
      id: "preset_showdown",
      name: "愤怒摊牌",
      template_ids: "TPL_F_001;TPL_M_001;TPL_SCENE_001",
      description: "门口对峙、酒红行李箱、写实短剧条漫风"
    },
    {
      id: "preset_luxury_romance",
      name: "豪门暗涌",
      template_ids: "TPL_F_002;TPL_M_002;TPL_STYLE_002",
      description: "冷调豪门、精英男女、克制冲突"
    },
    {
      id: "preset_light_comedy",
      name: "轻喜剧反转",
      template_ids: "TPL_UI_001;TPL_STORY_001",
      description: "对白气泡突出，适合短视频条漫阅读"
    }
  ],
  sheets: [
    {
      key: "README",
      label: "使用说明",
      group: "base",
      purpose: "说明整个 Excel 的使用规范。",
      columns: ["sheet_name", "purpose", "required", "owner", "update_frequency", "notes", "example"],
      rows: [
        { sheet_name: "field_registry", purpose: "字段总表", required: "TRUE", owner: "内容维护", update_frequency: "高", notes: "所有前台控件先在这里登记", example: "eye_shape" },
        { sheet_name: "rules_hard", purpose: "硬规则", required: "TRUE", owner: "规则维护", update_frequency: "中", notes: "禁止组合写在这里", example: "child + mature_makeup" }
      ]
    },
    {
      key: "meta_project",
      label: "项目配置",
      group: "base",
      purpose: "项目级全局配置。",
      columns: ["field_key", "field_value", "value_type", "notes"],
      rows: [
        { field_key: "project_name", field_value: "picfactory_newproject_v1", value_type: "string", notes: "项目名" },
        { field_key: "default_export_format", field_value: "json", value_type: "enum", notes: "默认导出格式" },
        { field_key: "image_base_path", field_value: "/assets/previews/", value_type: "path", notes: "预览图相对路径根目录" },
        { field_key: "enable_rules_engine", field_value: "TRUE", value_type: "boolean", notes: "启用规则校验" }
      ]
    },
    {
      key: "enum_constants",
      label: "枚举常量",
      group: "base",
      purpose: "所有枚举值统一管理。",
      columns: ["enum_type", "enum_value", "label", "sort_order", "enabled", "notes"],
      rows: [
        { enum_type: "role_type", enum_value: "female_lead", label: "女主", sort_order: "10", enabled: "TRUE", notes: "主角女性" },
        { enum_type: "role_type", enum_value: "male_lead", label: "男主", sort_order: "20", enabled: "TRUE", notes: "主角男性" },
        { enum_type: "ui_control", enum_value: "image_card_multi", label: "图片卡片多选", sort_order: "30", enabled: "TRUE", notes: "用于可视矩阵" },
        { enum_type: "rule_action", enum_value: "exclude", label: "排除", sort_order: "40", enabled: "TRUE", notes: "禁止组合" }
      ]
    },
    {
      key: "field_registry",
      label: "字段总表",
      group: "base",
      purpose: "系统字段总表，前台表单渲染核心表。",
      columns: ["field_id", "module", "sub_module", "field_key", "field_label", "data_type", "ui_control", "role_scope", "required", "allow_multiple", "option_source_sheet", "option_value_field", "option_label_field", "default_value", "placeholder", "group_name", "sort_order", "visible", "editable", "searchable", "filterable", "previewable", "validation_type", "validation_rule", "notes", "enabled"],
      rows: [
        { field_id: "FLD_001", module: "character", sub_module: "face", field_key: "eye_shape", field_label: "眼型", data_type: "string", ui_control: "image_card_multi", role_scope: "female_lead;male_lead", required: "TRUE", allow_multiple: "FALSE", option_source_sheet: "character_options_female_lead", option_value_field: "option_id", option_label_field: "label", default_value: "OPT_F_EYE_001", placeholder: "选择眼型", group_name: "面部", sort_order: "10", visible: "TRUE", editable: "TRUE", searchable: "TRUE", filterable: "TRUE", previewable: "TRUE", validation_type: "enum", validation_rule: "enabled=TRUE", notes: "主角面部差异核心字段", enabled: "TRUE" },
        { field_id: "FLD_002", module: "style", sub_module: "art", field_key: "main_art_style", field_label: "主画风", data_type: "string", ui_control: "select", role_scope: "all", required: "TRUE", allow_multiple: "FALSE", option_source_sheet: "art_style_options", option_value_field: "option_id", option_label_field: "label", default_value: "STYLE_001", placeholder: "选择画风", group_name: "画风", sort_order: "20", visible: "TRUE", editable: "TRUE", searchable: "TRUE", filterable: "TRUE", previewable: "TRUE", validation_type: "enum", validation_rule: "enabled=TRUE", notes: "影响整体提示词", enabled: "TRUE" },
        { field_id: "FLD_003", module: "scene", sub_module: "location", field_key: "scene_id", field_label: "场景", data_type: "string", ui_control: "image_card_single", role_scope: "all", required: "TRUE", allow_multiple: "FALSE", option_source_sheet: "scene_options", option_value_field: "scene_id", option_label_field: "label", default_value: "SCENE_001", placeholder: "选择场景", group_name: "场景", sort_order: "30", visible: "TRUE", editable: "TRUE", searchable: "TRUE", filterable: "TRUE", previewable: "TRUE", validation_type: "enum", validation_rule: "enabled=TRUE", notes: "场景矩阵入口", enabled: "TRUE" }
      ]
    },
    {
      key: "role_types",
      label: "角色类型",
      group: "base",
      purpose: "角色类型总表。",
      columns: ["role_type", "role_label", "description", "default_template_group", "icon", "sort_order", "enabled", "notes"],
      rows: [
        { role_type: "female_lead", role_label: "女主", description: "都市、古风、校园、豪门等主角女性", default_template_group: "urban_female", icon: "F", sort_order: "10", enabled: "TRUE", notes: "" },
        { role_type: "male_lead", role_label: "男主", description: "都市精英、少年感、霸总等主角男性", default_template_group: "elite_male", icon: "M", sort_order: "20", enabled: "TRUE", notes: "" },
        { role_type: "middle_older_woman", role_label: "中老年女性", description: "婆婆、母亲、贵妇等", default_template_group: "family_elder", icon: "E", sort_order: "30", enabled: "TRUE", notes: "" },
        { role_type: "child", role_label: "小孩", description: "儿童角色", default_template_group: "child", icon: "C", sort_order: "40", enabled: "TRUE", notes: "" }
      ]
    },
    {
      key: "character_options_female_lead",
      label: "女主原子项",
      group: "character",
      purpose: "女主所有原子选项。",
      columns: ["option_id", "role_type", "category", "sub_category", "label", "value_key", "description", "tags", "style_tags", "mood_tags", "genre_tags", "age_tags", "color_tags", "rarity", "default_weight", "priority", "enabled", "preview_image", "thumbnail_image", "pair_hint", "exclude_hint", "notes"],
      rows: [
        { option_id: "OPT_F_EYE_001", role_type: "female_lead", category: "appearance", sub_category: "eye_shape", label: "明亮杏眼", value_key: "bright_almond_eyes", description: "眼睛明亮有神，适合都市言情", tags: "face;eye", style_tags: "realistic;romance", mood_tags: "soft;tension", genre_tags: "urban;romance", age_tags: "young_adult", color_tags: "", rarity: "common", default_weight: "1.0", priority: "90", enabled: "TRUE", preview_image: "/character/female/eye_001.png", thumbnail_image: "/character/female/eye_001_thumb.png", pair_hint: "light_makeup", exclude_hint: "", notes: "" },
        { option_id: "OPT_F_DRESS_001", role_type: "female_lead", category: "clothing", sub_category: "clothing_style", label: "浅青灰白改良旗袍", value_key: "celadon_qipao", description: "修身改良旗袍，淡雅花纹", tags: "qipao;urban", style_tags: "realistic;premium", mood_tags: "elegant;conflict", genre_tags: "urban;family", age_tags: "adult", color_tags: "celadon;white", rarity: "rare", default_weight: "1.2", priority: "95", enabled: "TRUE", preview_image: "/character/female/dress_qipao.png", thumbnail_image: "/character/female/dress_qipao_thumb.png", pair_hint: "low_bun;green_earring", exclude_hint: "sport_style", notes: "愤怒摊牌样例核心服装" },
        { option_id: "OPT_F_NAIL_001", role_type: "female_lead", category: "makeup", sub_category: "nail_style", label: "透明短甲", value_key: "clear_short_nails", description: "生活化、干净、不过度张扬", tags: "nail", style_tags: "realistic", mood_tags: "restrained", genre_tags: "urban", age_tags: "adult", color_tags: "clear", rarity: "common", default_weight: "0.8", priority: "60", enabled: "TRUE", preview_image: "/character/female/nail_clear.png", thumbnail_image: "/character/female/nail_clear_thumb.png", pair_hint: "", exclude_hint: "", notes: "" }
      ]
    },
    {
      key: "character_options_male_lead",
      label: "男主原子项",
      group: "character",
      purpose: "男主所有原子选项。",
      columns: ["option_id", "role_type", "category", "sub_category", "label", "value_key", "description", "tags", "style_tags", "mood_tags", "genre_tags", "age_tags", "color_tags", "rarity", "default_weight", "priority", "enabled", "preview_image", "thumbnail_image", "pair_hint", "exclude_hint", "notes"],
      rows: [
        { option_id: "OPT_M_FACE_001", role_type: "male_lead", category: "appearance", sub_category: "face_shape", label: "清晰下颌线", value_key: "sharp_jawline", description: "侧脸轮廓干净，都市精英感", tags: "face;jawline", style_tags: "realistic;premium", mood_tags: "cold;restrained", genre_tags: "urban;romance", age_tags: "adult", color_tags: "", rarity: "common", default_weight: "1.0", priority: "88", enabled: "TRUE", preview_image: "/character/male/face_jawline.png", thumbnail_image: "/character/male/face_jawline_thumb.png", pair_hint: "vest_suit", exclude_hint: "", notes: "" },
        { option_id: "OPT_M_CLOTH_001", role_type: "male_lead", category: "clothing", sub_category: "clothing_style", label: "深蓝灰西装马甲", value_key: "navy_gray_vest", description: "白衬衫搭配深蓝灰马甲", tags: "vest;suit", style_tags: "business;realistic", mood_tags: "controlled", genre_tags: "urban;rich_family", age_tags: "adult", color_tags: "navy;gray", rarity: "common", default_weight: "1.1", priority: "92", enabled: "TRUE", preview_image: "/character/male/vest_navy.png", thumbnail_image: "/character/male/vest_navy_thumb.png", pair_hint: "short_black_hair", exclude_hint: "streetwear", notes: "愤怒摊牌样例核心服装" }
      ]
    },
    {
      key: "character_options_middle_older_woman",
      label: "中老年女性原子项",
      group: "character",
      purpose: "婆婆、母亲、贵妇等原子项。",
      columns: ["option_id", "role_type", "category", "sub_category", "label", "value_key", "description", "tags", "style_tags", "mood_tags", "genre_tags", "age_tags", "color_tags", "rarity", "default_weight", "priority", "enabled", "preview_image", "thumbnail_image", "pair_hint", "exclude_hint", "notes"],
      rows: [
        { option_id: "OPT_E_001", role_type: "middle_older_woman", category: "temperament", sub_category: "temperament", label: "强势贵妇", value_key: "dominant_madame", description: "控制欲强，适合豪门冲突", tags: "elder;madame", style_tags: "premium", mood_tags: "pressure", genre_tags: "rich_family", age_tags: "middle_aged", color_tags: "", rarity: "common", default_weight: "1.0", priority: "70", enabled: "TRUE", preview_image: "/character/elder/madame.png", thumbnail_image: "/character/elder/madame_thumb.png", pair_hint: "pearl_necklace", exclude_hint: "", notes: "" }
      ]
    },
    {
      key: "character_options_child",
      label: "小孩原子项",
      group: "character",
      purpose: "小孩角色原子项。",
      columns: ["option_id", "role_type", "category", "sub_category", "label", "value_key", "description", "tags", "style_tags", "mood_tags", "genre_tags", "age_tags", "color_tags", "rarity", "default_weight", "priority", "enabled", "preview_image", "thumbnail_image", "pair_hint", "exclude_hint", "notes"],
      rows: [
        { option_id: "OPT_C_001", role_type: "child", category: "appearance", sub_category: "eye_shape", label: "圆润大眼", value_key: "round_bright_eyes", description: "儿童角色友好感", tags: "child;eye", style_tags: "soft", mood_tags: "innocent", genre_tags: "family", age_tags: "child", color_tags: "", rarity: "common", default_weight: "1.0", priority: "70", enabled: "TRUE", preview_image: "/character/child/eyes.png", thumbnail_image: "/character/child/eyes_thumb.png", pair_hint: "", exclude_hint: "mature_makeup", notes: "" }
      ]
    },
    {
      key: "character_templates",
      label: "人物模板",
      group: "character",
      purpose: "一键生成人设的模板。",
      columns: ["template_id", "template_name", "template_type", "role_type", "template_group", "description", "preferred_option_ids", "required_option_ids", "excluded_option_ids", "preferred_tags", "excluded_tags", "preferred_categories", "weight_multiplier", "priority", "preview_image", "thumbnail_image", "enabled", "notes"],
      rows: [
        { template_id: "TPL_F_001", template_name: "知性旗袍型女主", template_type: "character", role_type: "female_lead", template_group: "urban_female", description: "高挑纤细、浅青灰白旗袍、浅绿色长耳饰", preferred_option_ids: "OPT_F_EYE_001;OPT_F_DRESS_001", required_option_ids: "OPT_F_DRESS_001", excluded_option_ids: "sport_style", preferred_tags: "qipao;realistic;romance", excluded_tags: "cartoon", preferred_categories: "appearance;clothing;accessory", weight_multiplier: "1.2", priority: "96", preview_image: "/templates/female_qipao.png", thumbnail_image: "/templates/female_qipao_thumb.png", enabled: "TRUE", notes: "愤怒摊牌女主基底" },
        { template_id: "TPL_M_001", template_name: "冷静精英型男主", template_type: "character", role_type: "male_lead", template_group: "elite_male", description: "黑短发、白衬衫、深蓝灰马甲、克制气质", preferred_option_ids: "OPT_M_FACE_001;OPT_M_CLOTH_001", required_option_ids: "OPT_M_CLOTH_001", excluded_option_ids: "streetwear", preferred_tags: "business;restrained", excluded_tags: "cute", preferred_categories: "appearance;clothing;temperament", weight_multiplier: "1.1", priority: "94", preview_image: "/templates/male_elite.png", thumbnail_image: "/templates/male_elite_thumb.png", enabled: "TRUE", notes: "愤怒摊牌男主基底" }
      ]
    },
    {
      key: "art_style_options",
      label: "画风选项",
      group: "style",
      purpose: "画风、写实度、线条、渲染等原子项。",
      columns: ["option_id", "category", "sub_category", "label", "value_key", "description", "style_tags", "mood_tags", "genre_tags", "suitable_role_tags", "default_weight", "priority", "enabled", "preview_image", "thumbnail_image", "notes"],
      rows: [
        { option_id: "STYLE_001", category: "art_style", sub_category: "main_style", label: "AI写实趣味都市言情漫画", value_key: "realistic_urban_romance_comic", description: "真人质感影视短剧条漫分镜融合风", style_tags: "realistic;comic;short_drama", mood_tags: "dramatic;light_comedy", genre_tags: "urban;romance", suitable_role_tags: "adult;urban", default_weight: "1.3", priority: "98", enabled: "TRUE", preview_image: "/style/realistic_urban.png", thumbnail_image: "/style/realistic_urban_thumb.png", notes: "主推荐风格" },
        { option_id: "STYLE_002", category: "line", sub_category: "line_style", label: "弱线稿强体积", value_key: "soft_line_strong_volume", description: "不使用厚重二次元描边", style_tags: "realistic;soft_line", mood_tags: "premium", genre_tags: "all", suitable_role_tags: "all", default_weight: "1.0", priority: "86", enabled: "TRUE", preview_image: "/style/soft_line.png", thumbnail_image: "/style/soft_line_thumb.png", notes: "" }
      ]
    },
    {
      key: "color_palette_options",
      label: "配色方案",
      group: "style",
      purpose: "配色方案矩阵。",
      columns: ["palette_id", "palette_name", "main_colors", "accent_colors", "neutral_colors", "description", "style_tags", "mood_tags", "genre_tags", "default_weight", "priority", "enabled", "preview_image", "thumbnail_image", "notes"],
      rows: [
        { palette_id: "PAL_001", palette_name: "高级灰庭院光", main_colors: "#d8e4dc;#263746;#6b4d38", accent_colors: "#8d2834;#d9a84b", neutral_colors: "#f7f2e8;#363b3a", description: "浅青灰白、深蓝灰、木色、酒红行李箱", style_tags: "realistic;premium", mood_tags: "conflict;warm", genre_tags: "urban;family", default_weight: "1.2", priority: "95", enabled: "TRUE", preview_image: "/palette/courtyard_gray.png", thumbnail_image: "/palette/courtyard_gray_thumb.png", notes: "" }
      ]
    },
    {
      key: "lighting_options",
      label: "光影方案",
      group: "style",
      purpose: "光影方案矩阵。",
      columns: ["lighting_id", "label", "light_type", "contrast_level", "color_temperature", "directionality", "description", "style_tags", "mood_tags", "scene_tags", "default_weight", "priority", "enabled", "preview_image", "thumbnail_image", "notes"],
      rows: [
        { lighting_id: "LIGHT_001", label: "门外明亮门内阴影", light_type: "natural_plus_indoor", contrast_level: "high", color_temperature: "warm_daylight", directionality: "outside_to_inside", description: "门外阳光照亮女主，门内阴影压住男主", style_tags: "realistic;dramatic", mood_tags: "confrontation", scene_tags: "home;doorway", default_weight: "1.3", priority: "98", enabled: "TRUE", preview_image: "/lighting/doorway_contrast.png", thumbnail_image: "/lighting/doorway_contrast_thumb.png", notes: "" }
      ]
    },
    {
      key: "speech_bubble_options",
      label: "对白气泡",
      group: "style",
      purpose: "漫画对白气泡样式矩阵。",
      columns: ["bubble_id", "bubble_type", "label", "shape", "border_style", "tail_style", "fill_color", "text_color", "stroke_width", "corner_style", "description", "style_tags", "mood_tags", "genre_tags", "suitable_art_style_tags", "default_weight", "priority", "enabled", "preview_image", "thumbnail_image", "notes"],
      rows: [
        { bubble_id: "BUB_001", bubble_type: "normal_dialogue", label: "白底黑边圆角气泡", shape: "rounded", border_style: "solid_black", tail_style: "speaker_tail", fill_color: "#ffffff", text_color: "#111111", stroke_width: "2", corner_style: "soft_round", description: "清晰、短视频条漫可读", style_tags: "clean;comic", mood_tags: "dialogue", genre_tags: "all", suitable_art_style_tags: "realistic_urban_romance_comic", default_weight: "1.0", priority: "90", enabled: "TRUE", preview_image: "/ui/bubble_round.png", thumbnail_image: "/ui/bubble_round_thumb.png", notes: "" }
      ]
    },
    {
      key: "title_style_options",
      label: "标题样式",
      group: "style",
      purpose: "标题形式矩阵。",
      columns: ["title_style_id", "title_name", "structure_type", "layout_type", "decoration_type", "background_type", "color_style", "description", "style_tags", "mood_tags", "genre_tags", "suitable_art_style_tags", "default_weight", "priority", "enabled", "preview_image", "thumbnail_image", "notes"],
      rows: [
        { title_style_id: "TITLE_001", title_name: "短剧章回标题", structure_type: "main_plus_episode", layout_type: "top_left", decoration_type: "thin_line", background_type: "transparent", color_style: "ink_wine", description: "适合竖版条漫开场", style_tags: "editorial;comic", mood_tags: "dramatic", genre_tags: "urban;romance", suitable_art_style_tags: "realistic_urban_romance_comic", default_weight: "0.8", priority: "70", enabled: "TRUE", preview_image: "/ui/title_episode.png", thumbnail_image: "/ui/title_episode_thumb.png", notes: "" }
      ]
    },
    {
      key: "font_style_options",
      label: "字体样式",
      group: "style",
      purpose: "字体矩阵。",
      columns: ["font_id", "font_name", "font_family", "use_type", "weight_style", "outline_style", "shadow_style", "italic", "vertical_support", "description", "style_tags", "mood_tags", "genre_tags", "suitable_ui_tags", "suitable_art_style_tags", "default_weight", "priority", "enabled", "preview_image", "thumbnail_image", "font_file_ref", "notes"],
      rows: [
        { font_id: "FONT_001", font_name: "黑体对白", font_family: "SimHei", use_type: "dialogue", weight_style: "bold", outline_style: "none", shadow_style: "none", italic: "FALSE", vertical_support: "FALSE", description: "对白气泡用，清晰优先", style_tags: "clean", mood_tags: "dialogue", genre_tags: "all", suitable_ui_tags: "speech_bubble", suitable_art_style_tags: "all", default_weight: "1.0", priority: "88", enabled: "TRUE", preview_image: "/font/dialogue.png", thumbnail_image: "/font/dialogue_thumb.png", font_file_ref: "", notes: "" }
      ]
    },
    {
      key: "scene_options",
      label: "场景矩阵",
      group: "story",
      purpose: "场景矩阵。",
      columns: ["scene_id", "category", "sub_category", "label", "location_type", "description", "scene_tags", "mood_tags", "genre_tags", "time_tags", "suitable_role_tags", "default_weight", "priority", "enabled", "preview_image", "thumbnail_image", "notes"],
      rows: [
        { scene_id: "SCENE_001", category: "home", sub_category: "doorway", label: "家门口玄关", location_type: "residential_doorway", description: "门半开，门外庭院阳光，门内较暗", scene_tags: "home;doorway;courtyard", mood_tags: "confrontation;leaving", genre_tags: "urban;family", time_tags: "day", suitable_role_tags: "adult;couple", default_weight: "1.3", priority: "98", enabled: "TRUE", preview_image: "/scene/home_doorway.png", thumbnail_image: "/scene/home_doorway_thumb.png", notes: "愤怒摊牌核心场景" }
      ]
    },
    {
      key: "relationship_options",
      label: "关系矩阵",
      group: "story",
      purpose: "人物关系矩阵。",
      columns: ["relationship_id", "label", "relation_type", "description", "power_dynamic", "emotion_base", "genre_tags", "style_tags", "default_weight", "priority", "enabled", "notes"],
      rows: [
        { relationship_id: "REL_001", label: "夫妻冷战", relation_type: "couple", description: "长期积压后的摊牌", power_dynamic: "balanced_conflict", emotion_base: "anger;restraint", genre_tags: "urban;romance;family", style_tags: "short_drama", default_weight: "1.2", priority: "92", enabled: "TRUE", notes: "" }
      ]
    },
    {
      key: "emotion_options",
      label: "情绪矩阵",
      group: "story",
      purpose: "情绪矩阵。",
      columns: ["emotion_id", "label", "emotion_type", "intensity", "description", "mood_tags", "suitable_role_tags", "genre_tags", "default_weight", "priority", "enabled", "notes"],
      rows: [
        { emotion_id: "EMO_001", label: "怒气冲冲", emotion_type: "anger", intensity: "high", description: "眉头紧锁，嘴唇微张，情绪外放但不崩坏", mood_tags: "anger;showdown", suitable_role_tags: "female_lead", genre_tags: "urban;romance", default_weight: "1.1", priority: "90", enabled: "TRUE", notes: "" },
        { emotion_id: "EMO_002", label: "冷淡克制", emotion_type: "restraint", intensity: "medium", description: "双手插兜，压抑情绪", mood_tags: "cold;controlled", suitable_role_tags: "male_lead", genre_tags: "urban;romance", default_weight: "1.0", priority: "86", enabled: "TRUE", notes: "" }
      ]
    },
    {
      key: "plot_node_options",
      label: "剧情节点",
      group: "story",
      purpose: "剧情节点矩阵。",
      columns: ["plot_node_id", "label", "node_type", "conflict_level", "description", "genre_tags", "mood_tags", "suitable_scene_tags", "default_weight", "priority", "enabled", "notes"],
      rows: [
        { plot_node_id: "PLOT_001", label: "愤怒摊牌", node_type: "conflict_opening", conflict_level: "high", description: "女主拖着行李箱回娘家", genre_tags: "urban;family;romance", mood_tags: "anger;comedy_reverse", suitable_scene_tags: "home;doorway", default_weight: "1.3", priority: "96", enabled: "TRUE", notes: "样例剧情节点" }
      ]
    },
    {
      key: "rules_hard",
      label: "硬规则",
      group: "rules",
      purpose: "绝对禁止的组合规则。",
      columns: ["rule_id", "scope", "if_field", "if_operator", "if_value", "target_field", "action", "target_value", "message", "priority", "enabled", "notes"],
      rows: [
        { rule_id: "RH_001", scope: "character", if_field: "role_type", if_operator: "equals", if_value: "child", target_field: "makeup_style", action: "exclude", target_value: "mature_makeup", message: "儿童角色不能搭配成熟妆容", priority: "100", enabled: "TRUE", notes: "" },
        { rule_id: "RH_002", scope: "style", if_field: "main_art_style", if_operator: "contains", if_value: "realistic", target_field: "line_style", action: "exclude", target_value: "heavy_anime_outline", message: "写实风格不使用厚重二次元描边", priority: "95", enabled: "TRUE", notes: "" }
      ]
    },
    {
      key: "rules_binding",
      label: "绑定规则",
      group: "rules",
      purpose: "A 出现时优先 B。",
      columns: ["rule_id", "scope", "if_field", "if_operator", "if_value", "bind_field", "bind_operator", "bind_value", "bind_strength", "message", "priority", "enabled", "notes"],
      rows: [
        { rule_id: "RB_001", scope: "character", if_field: "clothing_style", if_operator: "equals", if_value: "celadon_qipao", bind_field: "hair_style", bind_operator: "prefer", bind_value: "low_bun", bind_strength: "high", message: "旗袍优先搭配低盘发", priority: "90", enabled: "TRUE", notes: "" },
        { rule_id: "RB_002", scope: "scene", if_field: "scene_id", if_operator: "equals", if_value: "SCENE_001", bind_field: "lighting_id", bind_operator: "prefer", bind_value: "LIGHT_001", bind_strength: "high", message: "门口玄关优先使用内外明暗对比光", priority: "88", enabled: "TRUE", notes: "" }
      ]
    },
    {
      key: "frontend_panels",
      label: "前台面板",
      group: "rules",
      purpose: "前台工厂面板定义。",
      columns: ["panel_id", "panel_key", "panel_label", "module", "sub_module", "sort_order", "visible", "collapsible", "default_expanded", "icon", "description", "enabled", "notes"],
      rows: [
        { panel_id: "PNL_001", panel_key: "role_selector", panel_label: "角色选择", module: "character", sub_module: "role", sort_order: "10", visible: "TRUE", collapsible: "FALSE", default_expanded: "TRUE", icon: "role", description: "选择女主、男主、配角类型", enabled: "TRUE", notes: "" },
        { panel_id: "PNL_002", panel_key: "appearance_editor", panel_label: "外形编辑", module: "character", sub_module: "appearance", sort_order: "20", visible: "TRUE", collapsible: "TRUE", default_expanded: "TRUE", icon: "face", description: "维护脸型、眼型、发型等", enabled: "TRUE", notes: "" },
        { panel_id: "PNL_003", panel_key: "style_editor", panel_label: "画风编辑", module: "style", sub_module: "art", sort_order: "30", visible: "TRUE", collapsible: "TRUE", default_expanded: "TRUE", icon: "style", description: "维护画风、配色、光影", enabled: "TRUE", notes: "" }
      ]
    },
    {
      key: "frontend_field_layout",
      label: "前台字段布局",
      group: "rules",
      purpose: "字段在前台的布局。",
      columns: ["layout_id", "panel_id", "field_key", "row_no", "col_no", "width_ratio", "sort_order", "visible", "highlighted", "description", "enabled", "notes"],
      rows: [
        { layout_id: "LAYOUT_001", panel_id: "PNL_002", field_key: "eye_shape", row_no: "1", col_no: "1", width_ratio: "1/2", sort_order: "10", visible: "TRUE", highlighted: "TRUE", description: "眼型卡片选择", enabled: "TRUE", notes: "" },
        { layout_id: "LAYOUT_002", panel_id: "PNL_003", field_key: "main_art_style", row_no: "1", col_no: "1", width_ratio: "1/1", sort_order: "20", visible: "TRUE", highlighted: "TRUE", description: "主画风下拉", enabled: "TRUE", notes: "" }
      ]
    },
    {
      key: "export_mapping",
      label: "导出映射",
      group: "rules",
      purpose: "Excel 字段到 JSON 的映射关系。",
      columns: ["mapping_id", "source_sheet", "source_column", "target_module", "target_json_path", "transform_type", "split_separator", "default_if_empty", "enabled", "notes"],
      rows: [
        { mapping_id: "MAP_001", source_sheet: "character_options_female_lead", source_column: "option_id", target_module: "characters", target_json_path: "$.characters.options[].id", transform_type: "string", split_separator: "", default_if_empty: "", enabled: "TRUE", notes: "" },
        { mapping_id: "MAP_002", source_sheet: "character_templates", source_column: "preferred_option_ids", target_module: "templates", target_json_path: "$.templates[].preferred_option_ids", transform_type: "array_split", split_separator: ";", default_if_empty: "[]", enabled: "TRUE", notes: "" },
        { mapping_id: "MAP_003", source_sheet: "scene_options", source_column: "scene_tags", target_module: "scenes", target_json_path: "$.scenes[].tags", transform_type: "array_split", split_separator: ";", default_if_empty: "[]", enabled: "TRUE", notes: "" }
      ]
    }
  ]
};
