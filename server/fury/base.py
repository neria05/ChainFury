import os
import json
import inspect
import logging
import traceback
from hashlib import sha256
from typing import Any, Union, Optional, Dict, List, Tuple, Callable
from collections import deque, defaultdict

import jinja2schema
from jinja2schema import model as j2sm


def get_logger():
    logger = logging.getLogger("fury")
    lvl = os.getenv("FURY_LOG_LEVEL", "info").upper()
    logger.setLevel(getattr(logging, lvl))
    log_handler = logging.StreamHandler()
    log_handler.setFormatter(
        logging.Formatter("[%(asctime)s] [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z")
    )
    logger.addHandler(log_handler)
    return logger


logger = get_logger()


class Secret(str):
    """This class just means that in Var it will be taken as a password field"""


#
# Vars: this is the base class for all the fields that the user can provide from the front end
#


class Var:
    def __init__(
        self,
        type: Union[str, List["Var"]],
        format: str = "",
        items: List["Var"] = [],
        additionalProperties: Union[List["Var"], "Var"] = [],
        password: bool = False,
        #
        required: bool = False,
        placeholder: str = "",
        show: bool = False,
        name: str = "",
        *,
        _loc: Optional[Tuple] = (),
    ):
        self.type = type
        self.format = format
        self.items = items or []
        self.additionalProperties = additionalProperties
        self.password = password
        #
        self.required = required
        self.placeholder = placeholder
        self.show = show
        self.name = name
        #
        self.value = None
        self._loc = _loc  # this is the location from which this value is extracted

    def __repr__(self) -> str:
        return f"Var({'*' if self.required else ''}'{self.name}', type={self.type}, items={self.items}, additionalProperties={self.additionalProperties})"

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"type": self.type}
        if type(self.type) == list and len(self.type) and type(self.type[0]) == Var:
            d["type"] = [x.to_dict() for x in self.type]
        if self.format:
            d["format"] = self.format
        if self.items:
            d["items"] = [item.to_dict() for item in self.items]
        if self.additionalProperties:
            if isinstance(self.additionalProperties, Var):
                d["additionalProperties"] = self.additionalProperties.to_dict()
            else:
                d["additionalProperties"] = self.additionalProperties
        if self.password:
            d["password"] = self.password
        #
        if self.required:
            d["required"] = self.required
        if self.placeholder:
            d["placeholder"] = self.placeholder
        if self.show:
            d["show"] = self.show
        if self.name:
            d["name"] = self.name
        return d

    def set_value(self, v: Any):
        self.value = v


def pyannotation_to_json_schema(x, allow_any, allow_exc, allow_none, *, trace: bool = False) -> Var:
    """Function to convert the given annotation from python to a Var which can then be
    JSON serialised and sent to the clients."""
    if isinstance(x, type):
        if trace:
            logger.debug("t0")

        if x == str:
            return Var(type="string")
        elif x == int or x == float:
            return Var(type="number")
        elif x == bool:
            return Var(type="boolean")
        elif x == bytes:
            return Var(type="string", format="byte")
        elif x == list:
            return Var(type="array", items=[Var(type="string")])
        elif x == dict:
            return Var(type="object", additionalProperties=Var(type="string"))

        # there are some types that are unique to the fury system
        elif x == Secret:
            return Var(type="string", password=True)
        elif x == Model:
            return Var(type=Model.type_name, required=False, show=False)
        if x == Exception and allow_exc:
            return Var(type="exception", required=False, show=False)
        elif x == type(None) and allow_none:
            return Var(type="null", required=False, show=False)
        else:
            raise ValueError(f"i0: Unsupported type: {x}")
    elif isinstance(x, str):
        if trace:
            logger.debug("t1")
        return Var(type="string")
    elif hasattr(x, "__origin__") and hasattr(x, "__args__"):
        if trace:
            logger.debug("t2")
        if x.__origin__ == list:
            if trace:
                logger.debug("t2.1")
            return Var(
                type="array",
                items=[pyannotation_to_json_schema(x.__args__[0], allow_any, allow_exc, allow_none)],
            )
        elif x.__origin__ == dict:
            if len(x.__args__) == 2 and x.__args__[0] == str:
                if trace:
                    logger.debug("t2.2")
                return Var(
                    type="object",
                    additionalProperties=pyannotation_to_json_schema(x.__args__[1], allow_any, allow_exc, allow_none),
                )
            else:
                raise ValueError(f"i2: Unsupported type: {x}")
        elif x.__origin__ == tuple:
            if trace:
                logger.debug("t2.3")
            return Var(
                type="array",
                items=[pyannotation_to_json_schema(arg, allow_any, allow_exc, allow_none) for arg in x.__args__],
            )
        elif x.__origin__ == Union:
            # Unwrap union types with None type
            types = [arg for arg in x.__args__ if arg is not None]
            if len(types) == 1:
                if trace:
                    logger.debug("t2.4")
                return pyannotation_to_json_schema(types[0], allow_any, allow_exc, allow_none)
            else:
                if trace:
                    logger.debug("t2.5")
                return Var(type=[pyannotation_to_json_schema(typ, allow_any, allow_exc, allow_none) for typ in types])
        else:
            raise ValueError(f"i3: Unsupported type: {x}")
    elif isinstance(x, tuple):
        if trace:
            logger.debug("t4")
        return Var(
            type="array",
            items=[
                Var(type="string"),
                pyannotation_to_json_schema(x[1], allow_any, allow_exc, allow_none),
            ]
            * len(x),
        )
    elif x == Any and allow_any:
        if trace:
            logger.debug("t5")
        return Var(type="string")
    else:
        if trace:
            logger.debug("t6")
        raise ValueError(f"i4: Unsupported type: {x}")


def func_to_vars(func) -> List[Var]:
    """
    Extracts the signature of a function and converts it to an array of Var objects.
    """
    signature = inspect.signature(func)
    fields = []
    for param in signature.parameters.values():
        schema = pyannotation_to_json_schema(param.annotation, allow_any=False, allow_exc=False, allow_none=False)
        schema.required = param.default is inspect.Parameter.empty
        schema.name = param.name
        schema.placeholder = str(param.default) if param.default is not inspect.Parameter.empty else ""
        if not schema.name.startswith("_"):
            schema.show = True
        fields.append(schema)
    return fields


def func_to_return_vars(func, returns: Dict[str, Tuple]) -> List[Var]:
    """
    Analyses the return annotation type of the signature of a function and converts it to an array of
    named Var objects.
    """
    signature = inspect.signature(func)
    schema = pyannotation_to_json_schema(signature.return_annotation, allow_any=True, allow_exc=True, allow_none=True)
    if not (
        schema.type == "array"
        and len(schema.items) == 2
        and type(schema.items[1].type) == list
        and any(x.type == "exception" for x in schema.items[1].type)
    ):
        raise ValueError("Interface requires return type Tuple[..., Optional[Exception]] where ... is JSON serializable")

    # take the names provided in returns and populate the returning field
    logger.debug(f"RETURNS: {returns}")
    ret = schema.items[0]
    logger.debug(f"RET: {ret}")
    if ret.type == "array":
        assert len(returns) in [1, len(ret.items)], f"For array outputs, returns should either be 1 or {len(ret.items)}, got {len(returns)}"
        if len(returns) == 1:
            ret.items[0].name = next(iter(returns))
            ret.items[0]._loc = returns[next(iter(returns))]
        for i, n in zip(ret.items, returns):
            i.name = n
            i._loc = returns[n]
        ret = ret.items
    else:
        assert len(returns) == 1, "Items that are not arrays can have only 1 returning var. This can also be a bug"
        ret.name = next(iter(returns))
        ret._loc = returns[next(iter(returns))]
        ret = [
            ret,
        ]
    logger.debug(f"FINAL: {ret}")
    return ret


def jinja_schema_to_vars(v) -> Var:
    if type(v) == j2sm.Scalar or type(v) == j2sm.String:
        field = Var(type="string", required=True)
    elif type(v) == j2sm.Number:
        field = Var(type="number", required=True)
    elif type(v) == j2sm.Boolean:
        field = Var(type="boolean", required=True)
    elif type(v) == j2sm.Unknown:
        field = Var(type="string", required=True)
    elif type(v) == j2sm.Variable:
        field = Var(type="string", required=True)
    elif type(v) == j2sm.Dictionary:
        field = Var(type="object", required=True)
        all_fields = []
        for k, v in v.items():
            field_item = jinja_schema_to_vars(v)
            field_item.name = k
            all_fields.append(field_item)
        field.additionalProperties = all_fields
    elif type(v) == j2sm.List:
        field = Var(type="array", required=True)
        field.items = [jinja_schema_to_vars(v.item)]
    elif type(v) == j2sm.Tuple:
        field = Var(type="array", required=True)
        if v.items:
            field.items = [jinja_schema_to_vars(x) for x in v.items]
    else:
        raise ValueError(f"cannot handle type {type(v)}")
    return field


def jtype_to_vars(prompt: str) -> List[Var]:
    try:
        s = jinja2schema.infer(prompt)
        fields = []
        for k, v in s.items():
            f = jinja_schema_to_vars(v)
            f.name = k
            fields.append(f)
    except Exception as e:
        logger.error(
            "Could not parse prompt to jinja schema. We support only for/if/filters in jinja2. "
            "Please read here for more information: https://jinja.palletsprojects.com/en/3.1.x/templates/"
        )
        raise e
    return fields


def extract_jinja_indices(data, current_index=(), indices=None) -> List:
    """
    Returns things like:

    [(('3', 'content'), [Var('num1', type=string, items=[], additionalProperties=[]), Var('num2', type=string, items=[], additionalProperties=[])])]
    [((), [Var('message', type=string, items=[], additionalProperties=[])])]
    [(('meta_prompt', 'data'), [Var('place', type=string, items=[], additionalProperties=[])])]
    [('0', [Var('name', type=string, items=[], additionalProperties=[])])]
    [(('meta', 'ptype'), [Var('genome', type=string, items=[], additionalProperties=[])])]
    [(('level-0', 'level-1', 'level-2'), [Var('thing', type=string, items=[], additionalProperties=[])]), (('level-0', 'nice'), [Var('feeling', type=string, items=[], additionalProperties=[])])]
    []
    """
    if indices is None:
        indices = []

    if isinstance(data, str):
        fields = jtype_to_vars(data)
        if fields:
            indices.append((current_index, fields))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            if current_index:
                if type(current_index) == tuple:
                    new_index = (*current_index, i)
                else:
                    new_index = (current_index, i)
            else:
                new_index = str(i)
            extract_jinja_indices(item, new_index, indices)
    elif isinstance(data, dict):
        for key, value in data.items():
            if current_index:
                if type(current_index) == tuple:
                    new_index = (*current_index, key)
                else:
                    new_index = (current_index, key)
            else:
                new_index = key
            extract_jinja_indices(value, new_index, indices)

    return indices


def get_value_by_keys(obj, keys):
    if not keys:
        return obj
    keys = (keys,) if not isinstance(keys, (list, tuple)) else keys
    key = keys[0]
    if isinstance(obj, dict):
        return get_value_by_keys(obj.get(key), keys[1:])
    elif isinstance(obj, (list, tuple)):
        key = int(key)
        if isinstance(key, int) and 0 <= key < len(obj):
            return get_value_by_keys(obj[key], keys[1:])
    return None


def put_value_by_keys(obj, keys, value):
    if not keys:
        return

    keys = (keys,) if not isinstance(keys, (list, tuple)) else keys
    key = keys[0]
    if len(keys) == 1:
        if isinstance(obj, dict):
            obj[key] = value
        elif isinstance(obj, list) and isinstance(key, int) and 0 <= key < len(obj):
            obj[key] = value
    else:
        if isinstance(obj, dict):
            if key not in obj or not isinstance(obj[key], (dict, list)):
                obj[key] = {} if isinstance(keys[1], str) else []
            put_value_by_keys(obj[key], keys[1:], value)
        elif isinstance(obj, list) and isinstance(key, int) and 0 <= key < len(obj):
            if not isinstance(obj[key], (dict, list)):
                obj[key] = {} if isinstance(keys[1], str) else []
            put_value_by_keys(obj[key], keys[1:], value)


#
# Model: Each model is the processing engine of the AI actions. It is responsible for keeping
#        the state of each of the wrapped functions for different API calls.
#


class ModelTags:
    TEXT_TO_TEXT = "text_to_text"
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_IMAGE = "image_to_image"


class Model:
    model_tags = ModelTags
    type_name = "model"

    def __init__(
        self,
        collection_name,
        model_id,
        fn: object,
        description,
        vars: List[Var],
        tags=[],
    ):
        self.collection_name = collection_name
        self.model_id = model_id
        self.fn = fn
        self.description = description
        self.vars = vars
        self.tags = tags

    def __repr__(self) -> str:
        return f"Model('{self.collection_name}', '{self.model_id}')"

    def to_dict(self):
        return {
            "collection_name": self.collection_name,
            "model_id": self.model_id,
            "description": self.description,
            "tags": self.tags,
            "vars": [x.to_dict() for x in self.vars],
        }

    def __call__(self, model_data: Dict[str, Any]) -> Tuple[Any, Optional[Exception]]:
        try:
            out = self.fn(**model_data)  # type: ignore
            return out, None
        except Exception as e:
            return traceback.format_exc(), e


#
# Node: Each box that is drag and dropped in the UI is a Node, it will tell what kind of things are
#       its inputs, outputs and fields that are shown in the UI. It can be of different types and
#       it only wraps teh
#


class NodeType:
    PROGRAMATIC = "programatic"
    AI = "ai-powered"


class NodeConnection:
    def __init__(self, id: str, name: str = "", required: bool = False, description: str = ""):
        self.id = id
        self.name = name
        self.required = required
        self.description = description


class Node:
    types = NodeType()

    def __init__(
        self,
        id: str,
        type: str,
        fn: object,  # the function to call
        fields: List[Var],
        outputs: List[Var],
        description: str = "",
    ):
        # some bacic checks
        if type == NodeType.AI:
            pass
        elif type == NodeType.PROGRAMATIC:
            pass
        else:
            raise ValueError(f"Invalid node type: {type}, see Node.types for valid types")

        # set the values
        self.id = id
        self.type = type
        self.description = description
        self.fields = fields
        self.outputs = outputs
        self.fn = fn

    def __repr__(self) -> str:
        out = f"FuryNode{{ ('{self.id}', '{self.type}') ["
        for f in self.fields:
            if f.required:
                out += f"\n      {f},"
        out += f"\n] ({len(self.fields)}) => ({len(self.outputs)}) ["
        for o in self.outputs:
            out += f"\n      {o},"
        out += f"\n] }}"
        return out

    def has_field(self, field: str):
        return any([x.name == field for x in self.fields])

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "description": self.description,
            "fields": [field.to_dict() for field in self.fields],
            "outputs": [o.to_dict() for o in self.outputs],
        }

    def __call__(self, data: Dict[str, Any], ret_fields: bool = False) -> Tuple[Any, Optional[Exception]]:
        data_keys = set(data.keys())
        template_keys = set([x.name for x in self.fields])
        try:
            if not data_keys.issubset(template_keys):
                raise ValueError(f"Invalid keys passed to node: {data_keys - template_keys}")
            out, err = self.fn(**data)  # type: ignore
            if err:
                raise err
            # if not ret_fields:
            #     return out, None

            # this is where we have to polish this outgoing result into the structure as configured in self.outputs
            # print("> fnout: ", out)
            # print("OUTPUTS:", self.outputs)
            for o in self.outputs:
                # print("  OP:", o.name, o._loc)
                o.set_value(get_value_by_keys(out, o._loc))
            return {o.name: o.value for o in self.outputs}, None
        except Exception as e:
            tb = traceback.format_exc()
            return tb, e


#
# Edge: Each connection between two boxes on the UI is called an Edge, it is only a dataclass without any methods.
#


class Edge:
    def __init__(self, src_node_id: str, trg_node_id: str, *connections: Tuple[str, str]):
        # some basic checks
        for c in connections:
            assert isinstance(c, (tuple, list)), f"Invalid connection: {c}"
            assert len(c) == 2, f"Invalid connection: {c}"
            assert isinstance(c[0], str), f"Invalid connection: {c}"
            assert isinstance(c[1], str), f"Invalid connection: {c}"

        self.src_node_id = src_node_id
        self.trg_node_id = trg_node_id
        self.connections = connections

    def __repr__(self) -> str:
        out = f"FuryEdge('{self.src_node_id}' => '{self.trg_node_id}',"
        for c in self.connections:
            out += f"\n  {c[0]} -> {c[1]},"
        out += "\n)"
        return out

    def to_dict(self):
        return {
            "src_node_id": self.src_node_id,
            "trg_node_id": self.trg_node_id,
            "connections": self.connections,
        }


#
# Dag: An entire flow is called the Chain
#


class Chain:
    def __init__(
        self,
        nodes: List[Node] = [],
        edges: List[Edge] = [],
    ):
        self.nodes = {node.id: node for node in nodes}
        self.edges = edges
        self.topo_order = topological_sort(self.edges)

        for node_id in self.topo_order:
            assert node_id in self.nodes, f"Missing node from an edge: {node_id}"

    def __repr__(self) -> str:
        # return f"FuryDag(nodes: {len(self.nodes)}, edges: {len(self.edges)})"
        out = "FuryDag(\n  nodes: ["
        for n in self.nodes:
            out += f"\n    {n},"
        out += "\n  ],\n  edges: ["
        for e in self.edges:
            out += f"\n    {e},"
        out += "\n  ]\n)"
        return out

    def __call__(self, data, v: bool = False) -> Tuple[Var, Dict[str, Any]]:
        full_ir = {}
        out = None
        for node_id in self.topo_order:
            node = self.nodes[node_id]
            incoming_edges = list(filter(lambda edge: edge.trg_node_id == node_id, self.edges))

            # clear out all the nodes that this thing needs into a separate rep
            logger.debug(f"Processing node: {node_id}")
            logger.debug(f"Current full_ir: {set(full_ir.keys())}")
            _data = {}
            for edge in incoming_edges:
                # need to check if this information is available in the IR buffer, if it is not
                # then this is an error
                logger.debug(f"Incoming edge: {edge}")
                for conns in edge.connections:
                    req_key = f"{edge.src_node_id}/{conns[0]}"
                    logger.debug(f"Looking for key: {req_key}")
                    ir_value = full_ir.get(req_key, None)
                    if ir_value is None:
                        raise ValueError(f"Missing value for {req_key}")
                    _data[conns[1]] = ir_value

            all_keys = list(data.keys())
            for k in all_keys:
                if node.has_field(k):
                    _data[k] = data[k]  # don't pop this, some things are shared between actions eg. openai_api_key
            out, err = node(_data, ret_fields=True)
            if err:
                logger.error("TRACE:", out)
                raise err
            # if out.type != "array":
            #     out = Var(type="array", items=[out])
            for k, v in out.items():
                full_ir[f"{node_id}/{k}"] = v

        return out, full_ir  # type: ignore


#
# helper functions
#


class NotDAGError(Exception):
    pass


def edge_array_to_adjacency_list(edges: List[Edge]):
    """Convert silk format dag edges to adjacency list format"""
    adjacency_lists = {}
    for edge in edges:
        src = edge.src_node_id
        dst = edge.trg_node_id
        if src not in adjacency_lists:
            adjacency_lists[src] = []
        adjacency_lists[src].append(dst)
    return adjacency_lists


def adjacency_list_to_edge_map(adjacency_list) -> List[Edge]:
    """Convert adjacency list format to silk format dag edges"""
    edges = []
    for src, dsts in adjacency_list.items():
        for dst in dsts:
            edges.append(Edge(src_node_id=src, trg_node_id=dst))
    return edges


def topological_sort(edges: List[Edge]) -> List[str]:
    """Topological sort of a DAG, raises NotDAGError if the graph is not a DAG"""
    adjacency_lists = edge_array_to_adjacency_list(edges)
    in_degree = defaultdict(int)
    for src, dsts in adjacency_lists.items():
        for dst in dsts:
            in_degree[dst] += 1

    # Add all nodes with no incoming edges to the queue
    queue = deque()
    for node in adjacency_lists:
        if in_degree[node] == 0:
            queue.append(node)

    # For each node, remove it from the graph and add it to the sorted list
    sorted_list = []
    edge_nodes_cntr = 0
    while queue:
        node = queue.popleft()
        sorted_list.append(node)
        neighbours = adjacency_lists.get(node, [])
        if not neighbours:
            edge_nodes_cntr += 1
        for neighbor in neighbours:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # Check to see if all edges are removed
    if len(sorted_list) == len(adjacency_lists) + edge_nodes_cntr:
        return sorted_list
    else:
        raise NotDAGError("A cycle exists in the graph.")
