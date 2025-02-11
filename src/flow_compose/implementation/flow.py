# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
#  file, You can obtain one at https://mozilla.org/MPL/2.0/.
import inspect
from typing import Callable, Any, get_origin, Type

from flow_compose.extensions.makefun_extension import with_signature
from flow_compose.types import (
    FlowFunctionType,
    ReturnType,
)
from flow_compose.implementation.flow_function import (
    FlowFunction,
    Argument,
    FlowFunctionInvoker,
    FlowContext,
)


def annotation(
    _return_type: Type[ReturnType],
    **flow_functions_configuration: FlowFunction[Any],
) -> Callable[[FlowFunctionType], Callable[..., Any]]:
    def wrapper(wrapped_flow: FlowFunctionType) -> Callable[..., ReturnType]:
        all_parameters = inspect.signature(wrapped_flow).parameters.values()
        flow_functions_parameters: list[inspect.Parameter] = []
        non_flow_functions_parameters: list[inspect.Parameter] = []
        flow_function_arguments: set[str] = set()

        # the next flag tells us when we are in flow_function arguments
        flow_functions_argument_found = False
        for parameter in all_parameters:
            parameter_origin = get_origin(parameter.annotation)
            is_parameter_flow_function = (
                FlowFunction == parameter_origin
                or FlowFunction == parameter.annotation
                or isinstance(parameter.default, FlowFunction)
            )
            if not is_parameter_flow_function:
                if flow_functions_argument_found:
                    raise AssertionError(
                        "flow has to have all non-flow-function arguments before flow function arguments."
                    )
                if parameter.name in flow_functions_configuration:
                    raise AssertionError(
                        f"Argument `{parameter.name}` in flow `{wrapped_flow.__name__}`"
                        f" is not FlowFunction and"
                        f" is also present in the flow configuration."
                        f" Arguments that are not FlowFunction cannot be present in the flow configuration."
                    )
                non_flow_functions_parameters.append(parameter)
                continue

            flow_functions_argument_found = True

            parameter_origin = get_origin(parameter.annotation)
            is_parameter_argument = (
                Argument == parameter_origin
                or Argument == parameter.annotation
                or isinstance(parameter.default, Argument)
            )
            if is_parameter_argument:
                if isinstance(parameter.default, Argument):
                    parameter.default.name = parameter.name
                non_flow_functions_parameters.append(parameter)
                flow_function_arguments.add(parameter.name)

            flow_functions_parameters.append(parameter)

        flow_functions_argument_parameters_without_default: list[inspect.Parameter] = []
        flow_functions_argument_parameters_with_default: list[inspect.Parameter] = []
        non_flow_function_arguments: list[
            Argument[Any]
        ] = []  # Argument in configuration that are not flow argument
        for (
            flow_function_name,
            flow_function_configuration,
        ) in flow_functions_configuration.items():
            if not isinstance(flow_function_configuration, Argument):
                continue

            flow_function_configuration.name = flow_function_name

            if flow_function_name in flow_function_arguments:
                continue

            non_flow_function_arguments.append(flow_function_configuration)
            new_parameter = inspect.Parameter(
                name=flow_function_name,
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=flow_function_configuration.value_or_empty,
                annotation=flow_function_configuration.argument_type,
            )
            if flow_function_configuration.value_or_empty is inspect.Parameter.empty:
                flow_functions_argument_parameters_without_default.append(new_parameter)
            else:
                flow_functions_argument_parameters_with_default.append(new_parameter)

        @with_signature(
            func_name=wrapped_flow.__name__,
            func_signature=inspect.Signature(
                flow_functions_argument_parameters_without_default
                + non_flow_functions_parameters
                + flow_functions_argument_parameters_with_default
            ),
        )
        def flow_invoker(**kwargs: Any) -> ReturnType:
            flow_context = FlowContext()

            cached_flow_functions: list[FlowFunction[Any]] = []

            for configured_flow_function in flow_functions_configuration:
                flow_context[configured_flow_function] = FlowFunctionInvoker(
                    flow_function=flow_functions_configuration[
                        configured_flow_function
                    ],
                    flow_context=flow_context,
                )
                if flow_functions_configuration[configured_flow_function].cached:
                    cached_flow_functions.append(
                        flow_functions_configuration[configured_flow_function]
                    )

            missing_flow_arguments: list[str] = []
            for flow_function_parameter in flow_functions_parameters:
                if (
                    flow_function_parameter.name not in flow_context
                    and flow_function_parameter.default is inspect.Parameter.empty
                    and flow_function_parameter.name not in kwargs
                ):
                    missing_flow_arguments.append(flow_function_parameter.name)
                    continue

                if flow_function_parameter.name in kwargs:
                    flow_context[flow_function_parameter.name] = FlowFunctionInvoker(
                        flow_function=kwargs[flow_function_parameter.name],
                        flow_context=flow_context,
                    )

                else:
                    if flow_function_parameter.default is not inspect.Parameter.empty:
                        flow_context[flow_function_parameter.name] = (
                            FlowFunctionInvoker(
                                flow_function=flow_function_parameter.default,
                                flow_context=flow_context,
                            )
                        )

                        if flow_function_parameter.default.cached:
                            cached_flow_functions.append(
                                flow_function_parameter.default
                            )

                    kwargs[flow_function_parameter.name] = flow_context[
                        flow_function_parameter.name
                    ]

            if len(missing_flow_arguments) > 0:
                raise AssertionError(
                    f"`{'`, `'.join(missing_flow_arguments)}`"
                    f" {'FlowFunction is' if len(missing_flow_arguments) == 1 else 'FlowFunctions are'}"
                    f" required by the flow `{wrapped_flow.__name__}`"
                    f" but {'is' if len(missing_flow_arguments) == 1 else 'are'}"
                    f" missing in the flow context."
                )

            for non_flow_function_argument in non_flow_function_arguments:
                if non_flow_function_argument.name in kwargs:
                    non_flow_function_argument.value = kwargs[
                        non_flow_function_argument.name
                    ]
                    flow_context[non_flow_function_argument.name] = FlowFunctionInvoker(
                        flow_function=non_flow_function_argument,
                        flow_context=flow_context,
                    )
                    del kwargs[non_flow_function_argument.name]

            return wrapped_flow(**kwargs)

        return flow_invoker

    return wrapper
