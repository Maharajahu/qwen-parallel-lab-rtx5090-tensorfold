"""Use SM120 MXFP8 MMA with unit scales; keep the existing FP8 operands."""
from typing import Type
import cutlass
import cutlass.cute as cute


@cute.jit
def mma_m16n8k32_f32(
    a0: cutlass.Int32, a1: cutlass.Int32,
    a2: cutlass.Int32, a3: cutlass.Int32,
    b0: cutlass.Int32, b1: cutlass.Int32,
    c0: cutlass.Float32, c1: cutlass.Float32,
    c2: cutlass.Float32, c3: cutlass.Float32,
    ab_dtype: cutlass.Constexpr[Type[cutlass.Numeric]],
) -> tuple[cutlass.Float32, cutlass.Float32, cutlass.Float32, cutlass.Float32]:
    if cutlass.const_expr(ab_dtype != cutlass.Float8E4M3FN):
        raise TypeError('This isolated unit-scale experiment covers E4M3 only')
    # Keep accumulator bitcasts used by the installed legacy wrapper.
    # The scale is a register operand, never an additional memory load.
    return cute.arch.inline_ptx(
        '{ .reg .f32 fc<4>; .reg .b32 unit_scale; '
        'mov.b32 unit_scale, 0x7f7f7f7f; '
        'mov.b32 fc0, {$r6}; mov.b32 fc1, {$r7}; '
        'mov.b32 fc2, {$r8}; mov.b32 fc3, {$r9}; '
        'mma.sync.aligned.kind::mxf8f6f4.block_scale.scale_vec::1X.m16n8k32.row.col.f32.e4m3.e4m3.f32.ue8m0 '
        '{{$w0},{$w1},{$w2},{$w3}}, {{$r0},{$r1},{$r2},{$r3}}, {{$r4},{$r5}}, '
        '{fc0,fc1,fc2,fc3}, unit_scale, {0,0}, unit_scale, {0,0}; }',
        write_only_types=[cutlass.Float32]*4,
        read_only_args=[a0,a1,a2,a3,b0,b1,
                        c0.bitcast(cutlass.Int32),c1.bitcast(cutlass.Int32),
                        c2.bitcast(cutlass.Int32),c3.bitcast(cutlass.Int32)],
    )
