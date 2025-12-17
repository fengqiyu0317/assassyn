use crate::simulator::Simulator;
use sim_runtime::num_bigint::{BigInt, BigUint};
use sim_runtime::*;
use std::ffi::c_void;

// Elaborating module SimpleCounterInstance
pub fn SimpleCounterInstance(sim: &mut Simulator) -> bool {
  let current = { sim.cnt.payload[false as usize].clone() };
  let new_value = { ValueCastTo::<u32>::cast(&current) + ValueCastTo::<u32>::cast(&1u32) };
  // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./simple_counter.py:29
  print!("@line:{:<5} {:<10}: [SimpleCounterInstance]\t", line!(), cyclize(sim.stamp));
  println!("计数器值: {}", current,);
  // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./simple_counter.py:32
  {
    let stamp = sim.stamp - sim.stamp % 100 + 50;
    let write = ArrayWrite::new(stamp, false as usize, new_value.clone(), "SimpleCounterInstance");
    sim.cnt.write(0, write);
  };

  true
}
