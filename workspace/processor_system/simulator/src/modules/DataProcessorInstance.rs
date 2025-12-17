use crate::simulator::Simulator;
use sim_runtime::num_bigint::{BigInt, BigUint};
use sim_runtime::*;
use std::ffi::c_void;

// Elaborating module DataProcessorInstance
pub fn DataProcessorInstance(sim: &mut Simulator) -> bool {
  let data_in_valid = { !sim.DataProcessorInstance_data_in.is_empty() };
  let enable_valid = { !sim.DataProcessorInstance_enable.is_empty() };
  let data_in_and_enable_valid =
    { ValueCastTo::<bool>::cast(&data_in_valid) & ValueCastTo::<bool>::cast(&enable_valid) };
  // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./assassyn_example.py:49
  if !data_in_and_enable_valid {
    return false;
  };
  let data_in = {
    {
      let stamp = sim.stamp - sim.stamp % 100 + 50;
      sim
        .DataProcessorInstance_data_in
        .pop
        .push(FIFOPop::new(stamp, "DataProcessorInstance"));
      match sim.DataProcessorInstance_data_in.payload.front() {
        Some(value) => value.clone(),
        None => return false,
      }
    }
  };
  let enable = {
    {
      let stamp = sim.stamp - sim.stamp % 100 + 50;
      sim
        .DataProcessorInstance_enable
        .pop
        .push(FIFOPop::new(stamp, "DataProcessorInstance"));
      match sim.DataProcessorInstance_enable.payload.front() {
        Some(value) => value.clone(),
        None => return false,
      }
    }
  };
  let enable_eq = { ValueCastTo::<bool>::cast(&enable) == ValueCastTo::<bool>::cast(&true) };
  if enable_eq {
    let result = { ValueCastTo::<u64>::cast(&data_in) * ValueCastTo::<u64>::cast(&2u32) };
    // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./assassyn_example.py:60
    {
      let stamp = sim.stamp - sim.stamp % 100 + 50;
      let write = ArrayWrite::new(stamp, false as usize, result.clone(), "DataProcessorInstance");
      sim.processed_data.write(0, write);
    };
    // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./assassyn_example.py:63
    print!("@line:{:<5} {:<10}: [DataProcessorInstance]\t", line!(), cyclize(sim.stamp));
    println!("Processing: {} -> {}", data_in, result,);
  }
  let processed_data_rd = { sim.processed_data.payload[false as usize].clone() };
  // @/mnt/d/Tomato_Fish/豫文化课/新时代/大二秋/系统/assassyn/./assassyn_example.py:66
  print!("@line:{:<5} {:<10}: [DataProcessorInstance]\t", line!(), cyclize(sim.stamp));
  println!("Processed data available: {}", processed_data_rd,);

  true
}
